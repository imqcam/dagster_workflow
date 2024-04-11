"An example graph that just calls two ops, run as three different types of job"

# imports
from collections import Counter
from dagster import In, graph, op
from dagster_celery_k8s import celery_k8s_job_executor
from dagster_k8s import k8s_job_executor


@op(ins={"word": In(str)}, config_schema={"factor": int})
def multiply_the_word(context, word):
    return word * context.op_config["factor"]


@op(ins={"word": In(str)})
def count_letters(word):
    return dict(Counter(word))


@graph
def example_graph():
    count_letters(multiply_the_word())  # pylint: disable=no-value-for-parameter


example_job = example_graph.to_job(
    name="example_job",
    description="Example job. Use this to test your deployment.",
    config={
        "ops": {
            "multiply_the_word": {
                "inputs": {"word": "test"},
                "config": {"factor": 2},
            }
        }
    },
)

# pod_per_op_job = example_graph.to_job(
#     name="pod_per_op_job",
#     description="""
#     Example job that uses the `k8s_job_executor` to run each op in a separate pod.
#     """,
#     executor_def=k8s_job_executor,
#     config={
#         "ops": {
#             "multiply_the_word": {
#                 "inputs": {"word": "test"},
#                 "config": {"factor": 2},
#             },
#         },
#         "execution": {
#             "config": {
#                 "image_pull_policy": "Always",
#             }
#         },
#     },
# )

pod_per_op_celery_job = example_graph.to_job(
    name="pod_per_op_celery_job",
    description="""
    Example job that uses the `celery_k8s_job_executor` to send ops to Celery workers, which
    launch them in individual pods.
    """,
    executor_def=celery_k8s_job_executor,
    config={
        "ops": {
            "multiply_the_word": {
                "inputs": {"word": "test"},
                "config": {"factor": 2},
            },
        },
        "execution": {
            "config": {
                "image_pull_policy": "Always",
            }
        },
    },
)
