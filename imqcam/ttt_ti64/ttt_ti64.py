# imports
import pytz
from datetime import datetime
from dagster import op, graph, In, Out
from dagster_celery_k8s import celery_k8s_job_executor
import pandas as pd
from . import SinglePointSTK as SP

@op(
    ins={"input_path": In(str)},
    out={"output_path": Out(str)}
)
def run_ttt_ti64(context, input_path: str) -> str:
    # Specify the position time/temperature history
    df = pd.read_csv(input_path, header=0,
                names=["z position", "Time (s)", "Temperature"])
    df = df.pivot(index='Time (s)', columns='z position', values='Temperature')
    # Read the data into lists
    Times = list(df.index.values)
    zpos = list(df.columns.values)
    # Convert z from meters to millimeters
    zpos = [10**3*x for x in zpos]
    # Assuming a regular grid
    dz = zpos[1] - zpos[0]
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
    output = {'zpos[mm]':zpos, 'fracalpha':Fraca, 'fracGB':FracGB, 'fracBW':FracBW, 'fracCOL':FracCOL, 'fracMASS':FracMASS,  'fracMart':FracMART, 'tlath':Tlath}
    dfout = pd.DataFrame(output)
    # Output to a csv file using the time/temp history file and current date/time as a unique identifier
    # Get the timezone object for New York (Eastern time zone)
    tz_NY = pytz.timezone('America/New_York')
    # Get the current time in New York
    now = datetime.now(tz_NY)
    # Set the outputfilenama
    out_file = input_path.removesuffix('.csv') +'_out_' + now.strftime("%d%m%y_%H%M%S") + '.csv'
    dfout.to_csv(out_file)    
    return out_file

@graph
def ttt_ti64_graph():
    run_ttt_ti64()

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
                "inputs": {"input_path": "/imqcam_local_data/sample_z_time_temp.csv"},
            },
        },
        "execution": {
            "config": {
                "image_pull_policy": "Always",
            }
        },
    },
)
