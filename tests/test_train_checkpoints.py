"""Tests for the training CLI's default checkpoint callbacks.

The regression these guard against: last.ckpt came from save_last on the
val_mel callback, and Lightning only writes it when that callback has just
saved a top-k checkpoint. Once val_mel stopped making the top 5, last.ckpt
froze, and the epochs after it -- the end of the LR anneal -- were never saved
anywhere. A 2,000-epoch run's last.ckpt held epoch 1953.
"""

# _default_callbacks is what this module asserts about.
# pylint: disable=protected-access

import pytest

torch = pytest.importorskip("torch")
lightning = pytest.importorskip("lightning")
cli_module = pytest.importorskip("piper.train.__main__")

ModelCheckpoint = lightning.pytorch.callbacks.ModelCheckpoint
DataLoader = torch.utils.data.DataLoader
TensorDataset = torch.utils.data.TensorDataset


class _WorseningModel(lightning.LightningModule):  # type: ignore[name-defined]
    """Both monitored metrics get worse every epoch, so after the first five
    epochs no epoch ever enters a top-5."""

    def __init__(self) -> None:
        super().__init__()
        self.layer = torch.nn.Linear(2, 1)

    def training_step(self, batch, batch_idx):
        return self.layer(batch[0]).pow(2).mean()

    def validation_step(self, batch, batch_idx):
        self.log("val_mel", float(self.current_epoch))
        self.log("val_mos", -float(self.current_epoch))

    def configure_optimizers(self):
        return torch.optim.SGD(self.parameters(), lr=0.01)

    def train_dataloader(self):
        return DataLoader(TensorDataset(torch.randn(4, 2)), batch_size=2)

    def val_dataloader(self):
        return DataLoader(TensorDataset(torch.randn(2, 2)), batch_size=2)


def _fit(root, callbacks, max_epochs, ckpt_path=None):
    trainer = lightning.Trainer(
        max_epochs=max_epochs,
        callbacks=callbacks,
        default_root_dir=root,
        logger=False,
        enable_progress_bar=False,
        enable_model_summary=False,
        accelerator="cpu",
    )
    trainer.fit(_WorseningModel(), ckpt_path=ckpt_path)
    return root / "checkpoints"


def _epoch(path) -> int:
    return torch.load(path, map_location="cpu", weights_only=False)["epoch"]


def test_last_ckpt_is_the_final_epoch(tmp_path):
    checkpoints = _fit(tmp_path, cli_module._default_callbacks(), max_epochs=8)

    assert _epoch(checkpoints / "last.ckpt") == 7
    # The top-k checkpoints are unchanged: the five best are epochs 0-4.
    kept = sorted(p.name for p in checkpoints.glob("epoch=*-val_mel=*.ckpt"))
    assert [name.split("-")[0] for name in kept] == [f"epoch={e}" for e in range(5)]
    assert not list(checkpoints.glob("last-v*.ckpt"))


def test_resume_from_a_checkpoint_written_by_the_old_callbacks(tmp_path):
    # The callbacks as they were before last.ckpt got its own: save_last on
    # the val_mel callback, and nothing else writing last.ckpt.
    old_callbacks = [
        ModelCheckpoint(
            monitor="val_mel",
            mode="min",
            save_top_k=5,
            save_last=True,
            filename="epoch={epoch}-val_mel={val_mel:.4f}",
            auto_insert_metric_name=False,
        ),
        ModelCheckpoint(
            monitor="val_mos",
            mode="max",
            save_top_k=5,
            save_last=False,
            filename="epoch={epoch}-val_mos={val_mos:.4f}",
            auto_insert_metric_name=False,
        ),
    ]
    old = _fit(tmp_path / "old", old_callbacks, max_epochs=8)
    assert _epoch(old / "last.ckpt") == 4  # the bug: frozen at the last top-5 save

    new = _fit(
        tmp_path / "new",
        cli_module._default_callbacks(),
        max_epochs=10,
        ckpt_path=str(old / "last.ckpt"),
    )
    assert _epoch(new / "last.ckpt") == 9
