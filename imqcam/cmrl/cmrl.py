"An example of a CMRL workflow"

# imports
from globus_compute_sdk import Client, Executor
from globus_compute_sdk.serialize import CombinedCode
from dagster import graph, op
from dagster_celery_k8s import celery_k8s_job_executor


@op
def run_cmrl():
    endpoint_id = "f7475479-8822-4c1d-a909-9c15714f92bc"
    gc = Client(code_serialization_strategy=CombinedCode())
    print(f"Endpoint status: {gc.get_endpoint_status(endpoint_id)}")
    gce = Executor(endpoint_id=endpoint_id, client=gc)

    def testing():
        import os

        cmd = (
            "source ~/.bash_profile && "
            "cd /home/neminiz1/Maggie/CPFE/TestCaseInputs && "
            'singularity exec --bind "$(pwd):/scratch" ~/vanderbilt_240703.sif ./run_script.sh'
        )
        return os.popen(cmd).read()

    future = gce.submit(testing)
    print(future.result())


@graph
def cmrl_graph():
    run_cmrl()


cmrl_job = cmrl_graph.to_job(
    name="cmrl_example_job",
    description="Proof-of-concept CMRL workflow with Globus Compute",
    executor_def=celery_k8s_job_executor,
    config={
        "execution": {
            "config": {
                "image_pull_policy": "Always",
            }
        },
    },
)
