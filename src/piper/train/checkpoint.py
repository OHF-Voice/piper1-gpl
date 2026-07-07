"""Checkpoint utilities for Piper training."""

import inspect
import logging
import tempfile
import torch

_LOGGER = logging.getLogger(__name__)


def clean_checkpoint(checkpoint_path, target_num_speakers):
    """
    Clean and prepare a checkpoint for training. 
     - Removes invalid parameters from older training
     - Updates single speaker checkpoints for multi speaker
    """
    from .vits.lightning import VitsModel

    checkpoint = torch.load(checkpoint_path, weights_only=False, map_location="cpu")
    if "hyper_parameters" not in checkpoint:
        return checkpoint_path

    ckpt_updated = False
    hparams = checkpoint["hyper_parameters"]

    # Remove invalid params
    valid_params = set(inspect.signature(VitsModel.__init__).parameters.keys())
    invalid_params = set(hparams.keys()) - valid_params

    for param in invalid_params:
        _LOGGER.info(f"Removing invalid parameter '{param}' from checkpoint")
        del hparams[param]
        ckpt_updated = True

    # Prepare single-speaker checkpoint for multi-speaker training
    if target_num_speakers > 1:
        ckpt_num_speakers = hparams.get("num_speakers", 1)
        has_speaker_emb = any(
            k.startswith("model_g.emb_g.") for k in checkpoint.get("state_dict", {})
        )

        if ckpt_num_speakers == 1 and not has_speaker_emb:
            _LOGGER.info(
                f"Preparing single-speaker checkpoint for {target_num_speakers}-speaker training"
            )
            keys_to_keep = {"state_dict", "hyper_parameters", "pytorch-lightning_version"}
            keys_to_remove = [k for k in checkpoint.keys() if k not in keys_to_keep]
            for key in keys_to_remove:
                del checkpoint[key]
            ckpt_updated = True

    if not ckpt_updated:
        return checkpoint_path

    with tempfile.NamedTemporaryFile(suffix=".ckpt", delete=False) as f:
        torch.save(checkpoint, f.name)
        temp_path = f.name

    _LOGGER.info(f"Created cleaned checkpoint: {temp_path}")
    return temp_path
