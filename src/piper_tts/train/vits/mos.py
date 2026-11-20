"""Optional no-reference MOS prediction for validation audio.

Provides a perceptual-quality signal (``val_mos``) during training. Unlike the
adversarial GAN losses (``loss_g`` / ``loss_d``), which only reflect the
generator/discriminator equilibrium, a no-reference MOS predictor estimates how
a listener would rate the synthesized audio and tracks perceived quality.

The predictor is loaded lazily and all failures are non-fatal: if the backend
cannot be loaded (e.g. there is no network to download the checkpoint), MOS
logging is silently disabled and training proceeds unaffected.
"""

import logging
from typing import Optional

import torch

_LOGGER = logging.getLogger(__name__)

# tarepan/SpeechMOS UTMOS22 -- a strong, widely-used no-reference MOS predictor
# for synthetic speech. Loaded via torch.hub, which downloads and caches the
# checkpoint on first use. Pinned to a release tag for reproducibility.
_UTMOS_REPO = "tarepan/SpeechMOS:v1.2.0"
_UTMOS_MODEL = "utmos22_strong"


class MosPredictor:
    """Lazily-loaded, fail-safe no-reference MOS predictor."""

    def __init__(self, name: str = "utmos") -> None:
        self.name = name
        self._model = None
        self._disabled = False

    def _ensure_model(self) -> None:
        if (self._model is not None) or self._disabled:
            return

        try:
            if self.name == "utmos":
                model = torch.hub.load(_UTMOS_REPO, _UTMOS_MODEL, trust_repo=True)
                model.eval()
                self._model = model
            else:
                raise ValueError(f"Unknown MOS predictor: {self.name!r}")
        except Exception as exc:  # noqa: BLE001 - never let this break training
            _LOGGER.warning(
                "Could not load MOS predictor %r (%s); val_mos logging disabled",
                self.name,
                exc,
            )
            self._disabled = True

    @torch.inference_mode()
    def score(self, audio: torch.Tensor, sample_rate: int) -> Optional[float]:
        """Predicted MOS (~1-5) for a single mono waveform, or None if disabled.

        :param audio: Waveform tensor of any shape (flattened to mono).
        :param sample_rate: Sample rate of ``audio`` in Hz.
        """
        self._ensure_model()
        if self._model is None:
            return None

        # Predictor expects a batched mono waveform: shape [batch, time].
        device = next(self._model.parameters()).device
        wave = audio.detach().float().flatten().unsqueeze(0).to(device)

        try:
            score = self._model(wave, sample_rate)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            _LOGGER.warning("MOS scoring failed (%s); val_mos logging disabled", exc)
            self._disabled = True
            return None

        return float(torch.as_tensor(score).mean().item())
