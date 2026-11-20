"""Generate a test onnx voice model that generates silence.

Requires torch and onnx.
"""

import json
from pathlib import Path
from typing import Optional

import torch
from torch import nn

from piper_tts import PiperConfig

_DIR = Path(__file__).parent
_TESTS_DIR = _DIR
_TEST_VOICE = _TESTS_DIR / "test_voice.onnx"
_TEST_CONFIG = f"{_TEST_VOICE}.json"

OPSET_VERSION = 15


class TestGenerator(nn.Module):
    """Test voice that generates silence."""

    def __init__(self) -> None:
        """Initialize module."""
        super().__init__()

    def forward(
        self,
        text: torch.Tensor,
        text_lengths: torch.Tensor,
        scales: torch.Tensor,
        sid: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Generate silence."""
        # Use tensors so they will be exported
        audio = torch.zeros(size=(text.shape[0], 22050))  # 1 sec
        audio += text_lengths[0]
        audio += scales[0]

        # Silence
        audio.zero_()

        return audio.unsqueeze(1)


def main() -> None:
    """Export test voice."""
    with open(_TEST_CONFIG, "r", encoding="utf-8") as config_file:
        config_dict = json.load(config_file)
        config = PiperConfig.from_dict(config_dict)

    dummy_input_length = 50
    text = torch.randint(
        low=0, high=config.num_symbols, size=(1, dummy_input_length), dtype=torch.long
    )
    text_lengths = torch.tensor([text.size(1)], dtype=torch.int64)

    # noise, noise_w, length
    scales = torch.tensor([0.667, 1.0, 0.8], dtype=torch.float32)
    sid = torch.tensor([0], dtype=torch.int64)
    dummy_input = (text, text_lengths, scales, sid)

    model = TestGenerator()

    # Export
    torch.onnx.export(
        model=model,
        args=dummy_input,
        f=str(_TEST_VOICE),
        verbose=False,
        opset_version=OPSET_VERSION,
        input_names=["input", "input_lengths", "scales", "sid"],
        output_names=["output"],
        dynamic_axes={
            "input": {0: "batch_size", 1: "phonemes"},
            "input_lengths": {0: "batch_size"},
            "output": {0: "batch_size", 1: "time"},
        },
    )

    print(_TEST_VOICE)


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
