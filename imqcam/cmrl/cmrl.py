"An example of a CMRL workflow"

# imports
import concurrent.futures
from globus_compute_sdk import Client, Executor
from globus_compute_sdk.serialize import CombinedCode
from dagster import graph, op, In, Out, Nothing, MetadataValue
from dagster_celery_k8s import celery_k8s_job_executor
from ..resources.imqcam_girder_resource import IMQCAMGirderResource

# constants
DEF_ENDPOINT_ID = "f7475479-8822-4c1d-a909-9c15714f92bc"

# pylint: disable=unused-argument, import-outside-toplevel, multiple-imports, no-value-for-parameter


def get_globus_compute_executor(endpoint_id: str) -> Executor:
    """Create the Globus Compute client and return an Executor linked to the given
    endpoint ID (env vars for client ID and secret must be set)
    """
    gc = Client(code_serialization_strategy=CombinedCode())
    print(f"Endpoint status: {gc.get_endpoint_status(endpoint_id)}")
    return Executor(endpoint_id=endpoint_id, client=gc)


@op(ins={"remote_workdir_root": In(str), "endpoint_id": In(str)}, out=Out(str))
def create_remote_workdir(context, remote_workdir_root: str, endpoint_id: str) -> str:
    """Create the remote working directory for a specific run inside the given 'root' dir
    and return the path to it as a string
    """
    gce = get_globus_compute_executor(endpoint_id)

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
    return workdir_path_str


@op(
    ins={
        "workdir_path_str": In(str),
        "girder_input_folder": In(str),
        "endpoint_id": In(str),
    },
    out={"done": Out(Nothing)},
)
def copy_input_files(
    context,
    imqcam_girder: IMQCAMGirderResource,
    workdir_path_str: str,
    girder_input_folder: str,
    endpoint_id: str,
) -> None:
    """Copy all the files directly inside the "girder_input_folder" folder to the workdir
    at "workdir_path_str"
    """
    gce = get_globus_compute_executor(endpoint_id)
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
        for file_name, file_id in input_file_names_and_ids.items()
    ]
    concurrent.futures.wait(file_download_futures)


@op(
    ins={
        "workdir_path_str": In(str),
        "endpoint_id": In(str),
    },
    out={"done": Out(Nothing)},
)
def write_run_script(
    context,
    workdir_path_str: str,
    endpoint_id: str,
) -> None:
    """Write the run_script.sh file in the workdir and chmod it to be executable"""
    gce = get_globus_compute_executor(endpoint_id)

    def write_and_chmod_run_script(remote_workdir):
        import os, inspect, stat

        os.chdir(remote_workdir)
        run_script_text = inspect.cleandoc(
            r"""#!/bin/bash
            echo "setting env"
            source set_env.sh
            echo "loading module"
            ml standard/2023.0
            echo "running exe"
            mpirun -genv I_MPI_DEBUG=5 -launcher fork -np 4 /home/app/cmrl/bin/MainFiniteElementCmrl.exe
            echo "done"
            exit 0
            """
        )
        with open("run_script.sh", "w") as fp:
            fp.write(run_script_text)
        os.chmod(
            "run_script.sh",
            os.stat("run_script.sh").st_mode
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH,
        )

    future = gce.submit(write_and_chmod_run_script, workdir_path_str)
    print(future.result())


@op(
    ins={"workdir_path_str": In(str), "docker_image": In(str), "endpoint_id": In(str)},
    out={"done": Out(Nothing)},
)
def pull_docker_image(
    context,
    workdir_path_str: str,
    docker_image: str,
    endpoint_id: str,
) -> None:
    """Pull the given docker image using singularity on the remote Globus Compute node"""
    gce = get_globus_compute_executor(endpoint_id)

    def pull_image(remote_workdir, image):
        import os

        os.chdir(remote_workdir)
        cmd = f"singularity pull image.sif docker://{image}"
        return os.popen(cmd).read()

    pull_image_future = gce.submit(pull_image, workdir_path_str, docker_image)
    print(pull_image_future.result())


@op(
    ins={
        "workdir_path_str": In(str),
        "endpoint_id": In(str),
        "copy_input_done": In(Nothing),
        "write_run_script_done": In(Nothing),
        "image_pull_done": In(Nothing),
    },
    out=Out(str),
)
def run_cmrl_simulation(
    context,
    workdir_path_str: str,
    endpoint_id: str,
) -> str:
    """Hit the Globus compute endpoint to run the simulation through the downloaded
    docker image using singularity
    """
    gce = get_globus_compute_executor(endpoint_id)

    # run the simulation
    def run_simulation(remote_workdir):
        import os

        os.chdir(remote_workdir)
        cmd = (
            "source ~/.bash_profile && "
            'singularity exec --bind "$(pwd):/scratch" ./image.sif ./run_script.sh'
        )
        return os.popen(cmd).read()

    run_simulation_future = gce.submit(run_simulation, workdir_path_str)
    result = run_simulation_future.result()
    if context is not None:
        context.add_output_metadata(
            metadata={"simulation_output": MetadataValue.md(result)}
        )
    return result


@graph(
    ins={
        "remote_workdir_root": In(str),
        "girder_input_folder": In(str),
        "docker_image": In(str),
        "endpoint_id": In(str),
    }
)
def cmrl_graph(
    remote_workdir_root: str,
    girder_input_folder: str,
    docker_image: str,
    endpoint_id: str,
):
    "The ops above collected into a single graph"
    workdir_path_str = create_remote_workdir(
        remote_workdir_root=remote_workdir_root, endpoint_id=endpoint_id
    )
    copy_input_done = copy_input_files(
        workdir_path_str=workdir_path_str,
        girder_input_folder=girder_input_folder,
        endpoint_id=endpoint_id,
    )
    write_run_script_done = write_run_script(
        workdir_path_str=workdir_path_str,
        endpoint_id=endpoint_id,
    )
    image_pull_done = pull_docker_image(
        workdir_path_str=workdir_path_str,
        docker_image=docker_image,
        endpoint_id=endpoint_id,
    )
    # pylint: disable=unexpected-keyword-arg
    run_cmrl_simulation(
        workdir_path_str=workdir_path_str,
        endpoint_id=endpoint_id,
        copy_input_done=copy_input_done,
        write_run_script_done=write_run_script_done,
        image_pull_done=image_pull_done,
    )


cmrl_job = cmrl_graph.to_job(
    name="cmrl_example_job",
    description="Proof-of-concept CMRL workflow with Globus Compute",
    executor_def=celery_k8s_job_executor,
    config={
        "inputs": {
            "remote_workdir_root": "/home/neminiz1/remote_cmrl_workdir",
            "girder_input_folder": "Eminizer/cmrl_example/input",
            "docker_image": "archrockfish/vanderbilt:240703",
            "endpoint_id": DEF_ENDPOINT_ID,
        },
        "execution": {
            "config": {
                "image_pull_policy": "Always",
            }
        },
    },
)
