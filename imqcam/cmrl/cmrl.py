"An example of a JHU Computational Mechanics Research Laboratory (CMRL) workflow"

# imports
import pathlib
import base64
import concurrent.futures
from io import BytesIO
import pandas as pd
import matplotlib.pyplot as plt
from globus_compute_sdk import Client, Executor
from globus_compute_sdk.serialize import CombinedCode
from dagster import graph, op, In, Out, Nothing, MetadataValue
from dagster_celery_k8s import celery_k8s_job_executor
from ..resources.imqcam_girder_resource import IMQCAMGirderResource

# constants
DEF_ENDPOINT_ID = "f7475479-8822-4c1d-a909-9c15714f92bc"

# pylint: disable=unused-argument, import-outside-toplevel, multiple-imports, no-value-for-parameter, redefined-outer-name, reimported


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

    def get_output_dir_path(remote_workdir):
        import pathlib

        output_dir_paths = [
            fp.resolve() for fp in pathlib.Path(remote_workdir).glob("analysis_*")
        ]
        if len(output_dir_paths) != 1:
            raise RuntimeError(
                f"ERROR: found {len(output_dir_paths)} simulation output directories in {remote_workdir}!"
            )
        return str(output_dir_paths[0])

    get_output_dir_future = gce.submit(get_output_dir_path, workdir_path_str)
    output_dir_path = get_output_dir_future.result()
    return output_dir_path


@op(
    ins={
        "output_dir_path": In(str),
        "girder_input_folder": In(str),
        "endpoint_id": In(str),
    },
    out=Out(str),
)
def copy_output_to_girder(
    context,
    imqcam_girder: IMQCAMGirderResource,
    output_dir_path: str,
    girder_input_folder: str,
    endpoint_id: str,
) -> None:
    """Use the Globus compute endpoint to recursively copy the output back to the Girder
    input folder
    """
    gce = get_globus_compute_executor(endpoint_id)

    def get_output_file_relative_paths(output_dir):
        import pathlib

        output_dir = pathlib.Path(output_dir)
        return [str(fp.resolve()) for fp in output_dir.rglob("*")]

    output_file_paths_future = gce.submit(
        get_output_file_relative_paths, output_dir_path
    )
    output_file_paths = output_file_paths_future.result()
    output_dir_path = pathlib.Path(output_dir_path)
    girder_input_folder = pathlib.Path(girder_input_folder)
    output_files_dict = {}
    for output_file_path in output_file_paths:
        output_file_path = pathlib.Path(output_file_path)
        girder_output_folder = f"{girder_input_folder}/{output_file_path.parent.relative_to(output_dir_path.parent)}"
        girder_output_folder_id = imqcam_girder.get_folder_id(
            girder_output_folder, create_if_not_found=True
        )
        output_files_dict[str(output_file_path)] = girder_output_folder_id

    def copy_file_to_girder(
        girder_api_url,
        girder_api_key,
        remote_file_path,
        girder_folder_id,
    ):
        import girder_client

        client = girder_client.GirderClient(apiUrl=girder_api_url)
        client.authenticate(apiKey=girder_api_key)
        client.uploadFileToFolder(girder_folder_id, remote_file_path)

    file_upload_futures = [
        gce.submit(
            copy_file_to_girder,
            imqcam_girder.api_url,
            imqcam_girder.api_key,
            output_file_path,
            girder_folder_id,
        )
        for output_file_path, girder_folder_id in output_files_dict.items()
    ]
    concurrent.futures.wait(file_upload_futures)
    return f"{girder_input_folder}/{output_dir_path.name}"


@op(ins={"girder_output_dir_path": In(str)})
def make_stress_strain_plot(
    context,
    imqcam_girder: IMQCAMGirderResource,
    girder_output_dir_path: str,
) -> None:
    """Make a stress/strain plot of the output and add it to the op's metadata as markdown"""
    girder_output_dir_path = pathlib.Path(girder_output_dir_path)
    stress_file_path = girder_output_dir_path / "output" / "volumetric_cauchystress.out"
    strain_file_path = girder_output_dir_path / "output" / "volumetric_truestrain.out"
    stress_df = imqcam_girder.get_dataframe_from_girder_csv_file(
        stress_file_path, delim_whitespace=True, header=None
    )
    strain_df = imqcam_girder.get_dataframe_from_girder_csv_file(
        strain_file_path, delim_whitespace=True, header=None
    )
    stress_strain_df = pd.DataFrame({"stress": stress_df[3], "strain": strain_df[3]})
    # Make the plot
    _, ax = plt.subplots(figsize=(6, 6))
    ax.plot(
        stress_strain_df["strain"], stress_strain_df["stress"], marker=".", color="k"
    )
    ax.set_xlabel("stress")
    ax.set_ylabel("strain")
    ax.set_title(pathlib.Path(girder_output_dir_path.name))
    # Save the figure image in the metadata
    plot_bytestream = BytesIO()
    plt.savefig(plot_bytestream, format="png", bbox_inches="tight")
    image_data = base64.b64encode(plot_bytestream.getvalue())
    md_content = f"![img](data:image/png;base64,{image_data.decode()})"
    if context is not None:
        context.add_output_metadata(metadata={"plot": MetadataValue.md(md_content)})


@op(
    ins={
        "workdir_path_str": In(str),
        "endpoint_id": In(str),
        "transfer_done": In(Nothing),
    }
)
def delete_remote_output_folder(
    context,
    workdir_path_str: str,
    endpoint_id: str,
) -> None:
    """Use Globus Compute to delete the output directory on the host system"""
    gce = get_globus_compute_executor(endpoint_id)

    def delete_dir(dirpath):
        import pathlib, shutil

        dirpath = pathlib.Path(dirpath)
        shutil.rmtree(dirpath)

    future = gce.submit(delete_dir, workdir_path_str)
    print(future.result)


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
    output_dir_path = run_cmrl_simulation(
        workdir_path_str=workdir_path_str,
        endpoint_id=endpoint_id,
        copy_input_done=copy_input_done,
        write_run_script_done=write_run_script_done,
        image_pull_done=image_pull_done,
    )
    girder_output_dir_path = copy_output_to_girder(
        output_dir_path=output_dir_path,
        girder_input_folder=girder_input_folder,
        endpoint_id=endpoint_id,
    )
    # pylint: disable=unexpected-keyword-arg
    delete_remote_output_folder(
        workdir_path_str=workdir_path_str,
        endpoint_id=endpoint_id,
        transfer_done=girder_output_dir_path,
    )
    make_stress_strain_plot(girder_output_dir_path=girder_output_dir_path)


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
