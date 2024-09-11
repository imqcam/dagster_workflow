"An example of a CMRL workflow"

# imports
import concurrent.futures
from globus_compute_sdk import Client, Executor
from globus_compute_sdk.serialize import CombinedCode
from dagster import graph, op, In
from dagster_celery_k8s import celery_k8s_job_executor
from ..resources.imqcam_girder_resource import IMQCAMGirderResource

# constants
DEF_ENDPOINT_ID = "f7475479-8822-4c1d-a909-9c15714f92bc"

# pylint: disable=import-outside-toplevel


@op(
    ins={
        "remote_workdir_root": In(str),
        "girder_input_folder": In(str),
        "docker_image": In(str),
        "endpoint_id": In(str),
    }
)
def run_cmrl(
    context,  # pylint: disable=unused-argument
    imqcam_girder: IMQCAMGirderResource,
    remote_workdir_root: str,
    girder_input_folder: str,
    docker_image: str,
    endpoint_id: str,
) -> None:
    # Create the Globus Compute client and Executor
    # (env vars for client ID and secret must be set)
    gc = Client(code_serialization_strategy=CombinedCode())
    print(f"Endpoint status: {gc.get_endpoint_status(endpoint_id)}")
    gce = Executor(endpoint_id=endpoint_id, client=gc)

    # create the remote workingdir
    def create_workdir(root_dir):
        import pathlib, datetime

        root_dir_path = pathlib.Path(root_dir)
        if not root_dir_path.is_dir():
            root_dir_path.mkdir(parents=True)
        workdir_path = (
            root_dir_path
            / f"cmrl_workdir_{datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}"
        )
        if workdir_path.is_dir():
            raise FileExistsError(
                f"ERROR: remote workdir {workdir_path} already exists!"
            )
        workdir_path.mkdir(parents=True)
        return str(workdir_path)

    create_workdir_future = gce.submit(create_workdir, remote_workdir_root)
    workdir_path_str = create_workdir_future.result()
    # copy files in the input folder on Girder to the remote workdir
    input_file_names_and_ids = imqcam_girder.get_folder_file_names_and_ids(
        girder_input_folder
    )

    def write_girder_file_to_workdir(
        girder_api_url, girder_api_key, remote_workdir, file_name, girder_file_id
    ):
        import pathlib
        import girder_client

        client = girder_client.GirderClient(apiUrl=girder_api_url)
        client.authenticate(apiKey=girder_api_key)
        file_contents = client.downloadFileAsIterator(girder_file_id)
        file_bytestring = b"".join(chunk for chunk in file_contents)
        with open(pathlib.Path(remote_workdir) / file_name, "wb") as fp:
            fp.write(file_bytestring)

    file_download_futures = [
        gce.submit(
            write_girder_file_to_workdir,
            imqcam_girder.api_url,
            imqcam_girder.api_key,
            workdir_path_str,
            file_name,
            file_id,
        )
        for file_name, file_id in input_file_names_and_ids
    ]
    concurrent.futures.wait(file_download_futures)

    # pull the image
    def pull_image(remote_workdir, image):
        import os

        os.chdir(remote_workdir)
        cmd = f"singularity pull image.sif docker://{image}"
        return os.popen(cmd).read()

    pull_image_future = gce.submit(pull_image, workdir_path_str, docker_image)
    print(pull_image_future.result())

    # run the simulation
    def run_simulation(remote_workdir):
        import os

        cmd = (
            "source ~/.bash_profile && "
            f"cd {remote_workdir} && "
            'singularity exec --bind "$(pwd):/scratch" image.sif ./run_script.sh'
        )
        return os.popen(cmd).read()

    run_simulation_future = gce.submit(run_simulation)
    print(run_simulation_future.result())


@graph
def cmrl_graph():
    # pylint: disable=no-value-for-parameter
    run_cmrl()


cmrl_job = cmrl_graph.to_job(
    name="cmrl_example_job",
    description="Proof-of-concept CMRL workflow with Globus Compute",
    executor_def=celery_k8s_job_executor,
    config={
        "ops": {
            "run_cmrl": {
                "inputs": {
                    "remote_workdir_root": "/home/neminiz1/remote_cmrl_workdir",
                    "girder_input_folder": "Eminizer/cmrl_example/input",
                    "docker_image": "archrockfish/vanderbilt:240703",
                    "endpoint_id": DEF_ENDPOINT_ID,
                },
            },
        },
        "execution": {
            "config": {
                "image_pull_policy": "Always",
            }
        },
    },
)
