# Dagster deployment in an unused node on the Kafka Kubernetes cluster

This directory contains files necessary to stand up [Dagster](https://dagster.io/) on a particular node of the [Kubernetes](https://kubernetes.io/) cluster that's also hosting the Elbert group's on-prem Kafka cluster. The deployment instructions below adapt the instructions and examples referenced [here](https://docs.dagster.io/deployment/guides/kubernetes/deploying-with-helm).

## Further details

These instructions describe how to deploy Dagster on the `kde04.idies.jhu.edu` node of the Kubernetes cluster that is also hosting the Elbert group's on-prem Kafka cluster. That cluster is deployed using Strimzi, and its three brokers are distributed across the `kde01`/`kde02`/`kde03.idies.jhu.edu` nodes, leaving the fourth relatively more empty for other applications such as this Dagster deployment. The cluster itself is accessible (i.e. with `kubectl` commands) from the BKI13 Linux system.

The dagster deployment is customized from the default Helm chart in that it uses a CeleryK8sRunLauncher (instead of a K8sRunLauncher) to launch tasks so that each step in a job gets executed in its own Kubernetes pod. It also includes an additional persistent volume and claim tethered to a particular NFS share (`sciserver-fs1:/srv/vc_crypt/IMQCAM/dagster_filesystem_io`) to handle I/O for jobs (the example linked above puts output in an S3 bucket instead).

To briefly explain how the deployment works, Dagster loads one or more "user code" servers that are linked to Docker images (currently stored on the openmsi DockerHub org). Those Docker images must have Dagster installed (along with its dependencies for running in k8s), and must have baked into them (i.e. the files copied into them, or a corresponding package installed in them) some Python module that acts as a Dagster "code location" with definitions of assets, ops, jobs, graphs, resources, etc. 

The different Dagster components are installed in k8s, along with the "user code" server, and the webserver UI can be used to launch jobs (jobs can also be run on defined schedules if desired, or by running "`kubectl exec`"-type commands in the dagster pods). Each step of each job is submitted to a celery queue backed by rabbit mq, and executed as a k8s Job. Logs are visible in the webserver UI, and output serialized/deserialized from tasks runs is saved to the disk referenced from the NFS share (this is just one possible type of I/O management).

## Tutorial

### Build and push the "user code" Docker image

The [imqcam](../imqcam/) directory in this repository is set up as an example of a Dagster "code location" using the [Definitions API](https://docs.dagster.io/_apidocs/definitions) (check the [__init__.py](../imqcam/__init__.py) file for what those Definitions are). To get that code location loaded into Dagster in k8s we first need to make a Docker image from it (including the dependencies for running Dagster in k8s) and push that to a registry. Here we'll use the the Dockerfile in that folder to build the image, and we'll push it to the `openmsi` Dockerhub organization.

Build and push the Docker image with the baked-in user code:

    cd dagster_workflow/imqcam
    docker build -t openmsi/testing_k8s_dagster .
    docker login
    docker push openmsi/testing_k8s_dagster

### Create the namespace in the cluster

Next, create a namespace to install dagster in:

    kubectl create namespace imqcam-dagster
    kubectl get namespaces

### Create the PV and PVC for the I/O manager to use

Dagster implements a number of different I/O managers that handle serializing and deserializing inputs and outputs between each of its tasks. The vanilla tutorial linked above uses an S3 bucket for this purpose, but I've edited the deployment to use a "[`FilesystemIOManager`](https://docs.dagster.io/_apidocs/io-managers#dagster.FilesystemIOManager)" instead, which I think is simpler. It also lets you see what the ser/des i/o looks like by storing it on a (presumably more accessible) filesystem.

We'll use a k8s yaml file to create a Persistent Volume and a Persistent Volume Claim pointing to a folder in an NFS share; it'll be mounted at `/tmp/imqcam_filesystem_io_data` inside every one of the Dagster pods in the cluster. 

Create the PersistentVolume for Dagster's FilesystemIOManager to use:

    kubectl apply -f dagster_filesystem_io_volume_and_claim.yaml
    kubectl get pv -n imqcam-dagster
    kubectl get pvc -n imqcam-dagster

### Create secrets

Some important values needed by DAGs are stored as Kubernetes Secrets. Those Secrets are created by the "`secrets.yaml`" file in this directory, and their values are not committed directly to this repository. For that reason, you'll need to edit the `secrets.yaml` file by hand after you've cloned this repository. That file has some values in it that read like "`base_64_encoded_*`"; you should replace those values with the base64-encoded real values of the Secrets that you need to create. To base64-encode a particular string, you can run:

    echo -n "string_to_encode" | base64 -b 0

You should know what the values for each of the Secrets should be, and then you should base64 encode those string values and replace the "`base_64_encoded_*`" values in the `secrets.yaml` file. After that's done, you can create the Secrets and add them to the cluster with:

    kubectl apply -f secrets.yaml

And check that they exist with:

    kubectl get secrets -n imqcam-dagster

### Install Dagster

We'll install Dagster in k8s using the Helm chart that Dagster makes publicly available. The [`values.yaml`](./values.yaml) file in this directory edits its default configurations to work as described above.

First, add the Dagster Helm chart repo:

    helm repo add dagster https://dagster-io.github.io/helm

Then install dagster referencing the custom `values.yaml` file:

    helm install dagster dagster/dagster -n imqcam-dagster --values values.yaml --debug

And that's all! But while I'm here: if you'd like to see what the default values.yaml file looks like (helpful for figuring out how to edit it), you can get your own copy of it with:

    helm show values dagster/dagster > default_values.yaml

(There's already a copy in the repo).

### Interacting with Dagster

You can open up the Dagster webserver UI by forwarding the port out of its pod. First, open a new window ssh'd to dsp057 with port 9000 forwarded:

    ssh dsp057 -L 9000:localhost:9000

Then, get the name of the webserver pod by running:

    kubectl get pods -n imqcam-dagster

And then forward the port with:

    kubectl -n imqcam-dagster port-forward [dagster-webserver-pod-name] 9000:80

Then you can pull up [localhost:9000](http://localhost:9000/) on your local machine to view the webserver.

One annoying thing is that Dagster doesn't automatically delete pods created for tasks that completed successfully, and it's up to the user to remove them every now and then. You can do that with:

    kubectl get pods -n imqcam-dagster --field-selector=status.phase==Succeeded -o=name | xargs kubectl delete -n imqcam-dagster

### Editing the install

When you make changes to the code location (anything inside the `imqcam` folder) you need to rebuild and push its Docker image, and then you need to restart the deployment for the code location server in k8s. Here's how to do that:

    cd dagster_workflow/imqcam
    docker build -t openmsi/testing_k8s_dagster . && docker login && docker push openmsi/testing_k8s_dagster
    kubectl rollout restart deployment dagster-dagster-user-deployments-imqcam-example-1 -n imqcam-dagster

When that's done running you should be able to reload the code location from the UI (or it might happen automatically) to see your new code location's jobs, etc. If there's a bug in the code you may need to debug the pod running the code location server.

K8s installs themselves can also be adjusted without uninstalling/reinstalling everything. You can edit the `values.yaml` file however you'd like, and then edit a running installation with:

    helm upgrade -f values.yaml dagster dagster/dagster -n imqcam-dagster --debug

K8s will figure out which pods need to be changed and it will remake them by itself without compromising the integrity of the overall installation.

### Clearing it all out

Uninstall dagster and delete the namespace with:

    helm uninstall dagster -n imqcam-dagster
    kubectl delete namespace imqcam-dagster
