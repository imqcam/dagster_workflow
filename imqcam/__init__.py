"Top-level definition for the dagster 'imqcam' module"

# imports
import os
from dagster import (
    Definitions,
    FilesystemIOManager,
)
from .resources.imqcam_girder_resource import IMQCAMGirderResource
from .example.example import example_job, pod_per_op_celery_job
from .ttt_ti64.ttt_ti64 import ttt_ti64_job

io_manager = FilesystemIOManager(base_dir="/tmp/imqcam_filesystem_io_data")

# read girder-related env vars
api_url = os.getenv("GIRDER_API_URL")
if api_url is None:
    raise RuntimeError("ERROR: no value set for 'GIRDER_API_URL' env var!")
api_key = os.getenv("GIRDER_API_KEY")
if api_key is None:
    raise RuntimeError("ERROR: no value set for 'GIRDER_API_KEY' env var!")

defs = Definitions(
    jobs=[example_job, pod_per_op_celery_job, ttt_ti64_job],
    resources={
        "io_manager": io_manager,
        "imqcam_girder": IMQCAMGirderResource(api_url=api_url, api_key=api_key),
    },
)
