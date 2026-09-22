import dataclasses

import einops
import numpy as np

from openpi import transforms
from openpi.models import model as _model


def make_ur5_example() -> dict:
    """Creates a random input example for the UR5 policy (test/inference plumbing)."""
    return {
        "observation/state": np.random.rand(7),
        "observation/base_image": np.random.randint(256, size=(480, 640, 3), dtype=np.uint8),
        "observation/wrist_image": np.random.randint(256, size=(480, 640, 3), dtype=np.uint8),
        "prompt": "pick up the drone",
    }


def _parse_image(image) -> np.ndarray:
    image = np.asarray(image)
    if np.issubdtype(image.dtype, np.floating):
        image = (255 * image).astype(np.uint8)
    if image.shape[0] == 3:
        image = einops.rearrange(image, "c h w -> h w c")
    return image


@dataclasses.dataclass(frozen=True)
class UR5Inputs(transforms.DataTransformFn):
    """Maps UR5 dataset/environment inputs into the model's expected format.
    Used for both training and inference.
    """

    model_type: _model.ModelType

    def __call__(self, data: dict) -> dict:
        # third_view (external, fixed) -> base_0_rgb ; head (wrist) -> left_wrist_0_rgb
        base_image = _parse_image(data["observation/base_image"])
        wrist_image = _parse_image(data["observation/wrist_image"])

        inputs = {
            # state = [6 joints (rad) + gripper (raw 0~1150)], already concatenated (7,).
            # No pad_to_dim here — padding is handled downstream, same as LiberoInputs.
            "state": data["observation/state"],
            "image": {
                "base_0_rgb": base_image,
                "left_wrist_0_rgb": wrist_image,
                # No right wrist -> zeros, masked out (for pi0/pi0.5).
                "right_wrist_0_rgb": np.zeros_like(base_image),
            },
            "image_mask": {
                "base_0_rgb": np.True_,
                "left_wrist_0_rgb": np.True_,
                "right_wrist_0_rgb": np.True_ if self.model_type == _model.ModelType.PI0_FAST else np.False_,
            },
        }

        if "actions" in data:
            inputs["actions"] = data["actions"]
        if "prompt" in data:
            inputs["prompt"] = data["prompt"]

        return inputs


@dataclasses.dataclass(frozen=True)
class UR5Outputs(transforms.DataTransformFn):
    """Maps model outputs back to the UR5 action space (inference only)."""

    def __call__(self, data: dict) -> dict:
        # 6 joints + 1 gripper = first 7 dims.
        return {"actions": np.asarray(data["actions"][..., :7])}