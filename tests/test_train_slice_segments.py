"""Tests for the vectorized segment slicing in the VITS training step.

``slice_segments`` used to loop over the batch and slice each utterance with a
start offset read back from a GPU tensor. Every read made the host wait for the
GPU, three times per training step. These tests pin the gather that replaced it
to the old loop's results, values and gradients alike.
"""

import pytest

torch = pytest.importorskip("torch")
commons = pytest.importorskip("piper.train.vits.commons")
losses = pytest.importorskip("piper.train.vits.losses")


def _loop_slice_segments(x, ids_str, segment_size):
    """The per-utterance loop that slice_segments replaced."""
    ret = torch.zeros_like(x[:, :, :segment_size])
    for i in range(x.size(0)):
        idx_str = max(0, int(ids_str[i]))
        idx_end = idx_str + segment_size
        ret[i] = x[i, :, idx_str:idx_end]
    return ret


@pytest.mark.parametrize(
    ("channels", "length", "segment_size"),
    [(1, 9000, 8192), (80, 120, 32), (192, 40, 32)],
)
def test_matches_loop_values_and_gradients(channels, length, segment_size):
    generator = torch.Generator().manual_seed(channels + length)
    x = torch.randn(6, channels, length, generator=generator)
    ids = torch.randint(-3, length - segment_size + 1, (6,), generator=generator)

    x_new = x.clone().requires_grad_()
    x_old = x.clone().requires_grad_()
    new = commons.slice_segments(x_new, ids, segment_size)
    old = _loop_slice_segments(x_old, ids, segment_size)
    assert torch.equal(new, old)

    upstream = torch.randn(new.shape, generator=generator)
    (new * upstream).sum().backward()
    (old * upstream).sum().backward()
    assert torch.equal(x_new.grad, x_old.grad)


def test_input_shorter_than_segment_keeps_input_width():
    # rand_slice_segments can only draw starts <= 0 here: lengths - segment < 0.
    x = torch.randn(3, 4, 10)
    ids = torch.tensor([-5, 0, -1])
    assert torch.equal(
        commons.slice_segments(x, ids, 32), _loop_slice_segments(x, ids, 32)
    )


def test_positions_past_the_end_read_as_zeros():
    # The old loop raised a shape mismatch here; padding is zeros anyway.
    x = torch.arange(1.0, 11.0).view(1, 1, 10)
    sliced = commons.slice_segments(x, torch.tensor([7]), 5)
    assert sliced.tolist() == [[[8.0, 9.0, 10.0, 0.0, 0.0]]]


def test_rand_slice_segments_stays_within_lengths():
    torch.manual_seed(0)
    x = torch.randn(5, 2, 50)
    lengths = torch.tensor([50, 40, 32, 33, 45])
    sliced, ids = commons.rand_slice_segments(x, lengths, 32)
    assert sliced.shape == (5, 2, 32)
    assert ids.device == x.device
    assert bool(((ids >= 0) & (ids + 32 <= lengths)).all())
    assert torch.equal(sliced, _loop_slice_segments(x, ids, 32))


def test_discriminator_loss_returns_detached_tensors():
    real = [torch.rand(2, 5, requires_grad=True) for _ in range(3)]
    fake = [torch.rand(2, 5, requires_grad=True) for _ in range(3)]
    loss, r_losses, g_losses = losses.discriminator_loss(real, fake)

    expected = sum(
        torch.mean((1 - r) ** 2) + torch.mean(g**2) for r, g in zip(real, fake)
    )
    assert torch.allclose(loss, expected)
    assert loss.requires_grad
    assert all(
        isinstance(v, torch.Tensor) and not v.requires_grad for v in r_losses + g_losses
    )
