"Top-level definition for the dagster 'tutorial' module"

# imports
from dagster import (
    Definitions,
    FilesystemIOManager,
)
from .example.example import example_job, pod_per_op_celery_job

io_manager = FilesystemIOManager(base_dir="/tmp/imqcam_filesystem_io_data")

defs = Definitions(
    jobs=[example_job, pod_per_op_celery_job],
    resources={
        "io_manager": io_manager,
    },
)
