# imports
import os
import pathlib
import base64
from io import BytesIO
from datetime import datetime
import pytz
from dagster import op, graph, In, Out, MetadataValue
from dagster_celery_k8s import celery_k8s_job_executor
import pandas as pd
import matplotlib.pyplot as plt
from ..resources.imqcam_girder_resource import IMQCAMGirderResource
from . import SinglePointSTK as SP


@op(ins={"input_path": In(str)}, out={"output_path": Out(str)})
# pylint: disable=unused-argument
def run_ttt_ti64(context, imqcam_girder: IMQCAMGirderResource, input_path: str) -> str:
    """Reads the input file from Girder, runs the analysis, writes the output csv file
    back to Girder, and returns the path to the file that was outputted
    """
    # Read the input file from Girder into a dataframe
    df = imqcam_girder.get_dataframe_from_girder_csv_file(input_path)
    # Rename the columns in the dataframe as read from the file
    df.columns = ["z position", "Time (s)", "Temperature"]
    # Specify the position time/temperature history
    df = df.pivot(index="Time (s)", columns="z position", values="Temperature")
    # Read the data into lists
    times = list(df.index.values)
    zpos = list(df.columns.values)
    # Convert z from meters to millimeters
    zpos = [10**3 * x for x in zpos]
    # compute the fractions of microstructure constituents for each position
    frac_alpha = []
    frac_gb = []
    frac_bw = []
    frac_col = []
    frac_mass = []
    frac_mart = []
    tlath = []
    for c in df.columns:
        temp_c = df[c]
        # Run the single point function
        thermal = SP.ThermalStep(times, temp_c)
        frac_alpha.append(thermal[0])
        frac_gb.append(thermal[1])
        frac_bw.append(thermal[2])
        frac_col.append(thermal[3])
        frac_mass.append(thermal[4])
        frac_mart.append(thermal[5])
        tlath.append(thermal[6])
    # This output is at the end of the time-temperature history
    output = {
        "zpos[mm]": zpos,
        "fracalpha": frac_alpha,
        "fracGB": frac_gb,
        "fracBW": frac_bw,
        "fracCOL": frac_col,
        "fracMASS": frac_mass,
        "fracMart": frac_mart,
        "tlath": tlath,
    }
    dfout = pd.DataFrame(output)
    # Output to a csv file using the time/temp history file and current date/time
    # as a unique identifier
    # Get the timezone object for New York (Eastern time zone)
    tz_ny = pytz.timezone(os.getenv("TZ", "America/New_York"))
    # Get the current time in New York
    now = datetime.now(tz_ny)
    # Set the outputfilename
    out_file = (
        input_path.removesuffix(".csv")
        + "_out_"
        + now.strftime("%d%m%y_%H%M%S")
        + ".csv"
    )
    # Write the dataframe back out as a new file in Girder
    imqcam_girder.write_dataframe_to_girder_file(dfout, out_file, index=False)
    return out_file


@op(ins={"input_path": In(str)})
def plot_ttt_ti64(
    context, imqcam_girder: IMQCAMGirderResource, input_path: str
) -> None:
    """Make a plot of the result and output it to the op's metadata as markdown"""
    # read the input result file
    df = imqcam_girder.get_dataframe_from_girder_csv_file(input_path)
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
    """The two ops above as a Graph"""
    # pylint: disable=no-value-for-parameter
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
