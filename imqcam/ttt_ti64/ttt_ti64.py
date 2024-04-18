# imports
import pytz
import pathlib
import base64
from io import BytesIO
from datetime import datetime
from dagster import op, graph, In, Out, MetadataValue
from dagster_celery_k8s import celery_k8s_job_executor
import pandas as pd
import matplotlib.pyplot as plt
from ..girder.girder_handling import (
    get_dataframe_from_girder_csv_file,
    write_dataframe_to_girder_file,
)
from . import SinglePointSTK as SP


@op(ins={"input_path": In(str)}, out={"output_path": Out(str)})
def run_ttt_ti64(context, input_path: str) -> str:
    # Read the input file from Girder into a dataframe
    df = get_dataframe_from_girder_csv_file(input_path)
    # Rename the columns in the dataframe as read from the file
    df.columns = ["z position", "Time (s)", "Temperature"]
    # Specify the position time/temperature history
    df = df.pivot(index="Time (s)", columns="z position", values="Temperature")
    # Read the data into lists
    Times = list(df.index.values)
    zpos = list(df.columns.values)
    # Convert z from meters to millimeters
    zpos = [10**3 * x for x in zpos]
    # compute the fractions of microstructure constituents for each position
    Fraca = []
    FracGB = []
    FracBW = []
    FracCOL = []
    FracMASS = []
    FracMART = []
    Tlath = []
    for c in df.columns:
        TempC = df[c]
        # Run the single point function
        Thermal = SP.ThermalStep(Times, TempC)
        Fraca.append(Thermal[0])
        FracGB.append(Thermal[1])
        FracBW.append(Thermal[2])
        FracCOL.append(Thermal[3])
        FracMASS.append(Thermal[4])
        FracMART.append(Thermal[5])
        Tlath.append(Thermal[6])
    # This output is at the end of the time-temperature history
    output = {
        "zpos[mm]": zpos,
        "fracalpha": Fraca,
        "fracGB": FracGB,
        "fracBW": FracBW,
        "fracCOL": FracCOL,
        "fracMASS": FracMASS,
        "fracMart": FracMART,
        "tlath": Tlath,
    }
    dfout = pd.DataFrame(output)
    # Output to a csv file using the time/temp history file and current date/time as a unique identifier
    # Get the timezone object for New York (Eastern time zone)
    tz_NY = pytz.timezone("America/New_York")
    # Get the current time in New York
    now = datetime.now(tz_NY)
    # Set the outputfilename
    out_file = (
        input_path.removesuffix(".csv")
        + "_out_"
        + now.strftime("%d%m%y_%H%M%S")
        + ".csv"
    )
    # Write the dataframe back out as a new file in Girder
    write_dataframe_to_girder_file(out_file, dfout)
    return out_file


@op(ins={"input_path": In(str)})
def plot_ttt_ti64(context, input_path: str) -> None:
    # read the input result file
    df = get_dataframe_from_girder_csv_file(input_path)
    # Make the plot
    f, ax = plt.subplots(2, 1, figsize=(2 * 4, 6), sharex=True)
    for colname in df.columns:
        if colname in ("zpos[mm]", "tlath"):
            continue
        ax[0].plot(df["zpos[mm]"], df[colname], marker=".", label=colname)
    ax[1].plot(df["zpos[mm]"], df["tlath"], marker=".", color="k")
    ax[0].legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    ax[0].set_ylabel("fraction")
    ax[1].set_xlabel("z position (mm)")
    ax[1].set_ylabel(r"$\alpha$ lath spacing ($\mu$m)")
    f.suptitle(pathlib.Path(input_path).name)
    # Save the figure image in the metadata
    plot_bytestream = BytesIO()
    plt.savefig(plot_bytestream, format="png", bbox_inches="tight")
    image_data = base64.b64encode(plot_bytestream.getvalue())
    md_content = f"![img](data:image/png;base64,{image_data.decode()})"
    if context is not None:
        context.add_output_metadata(metadata={"plot": MetadataValue.md(md_content)})


@graph
def ttt_ti64_graph():
    plot_ttt_ti64(run_ttt_ti64())


ttt_ti64_job = ttt_ti64_graph.to_job(
    name="ttt_ti64_job",
    description="""
    Runs Bryan Webler's group's Time-Temperature-Transformation model for Ti-6Al-4V
    alloys code on a given input file
    """,
    executor_def=celery_k8s_job_executor,
    config={
        "ops": {
            "run_ttt_ti64": {
                "inputs": {
                    "input_path": "Eminizer/webler_ttt_ti64_example/sample_z_time_temp.csv"
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
