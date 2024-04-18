# Testing Dagster deployment with a local Kubernetes cluster

This directory contains files necessary to stand up [Dagster](https://dagster.io/) in a local [Kubernetes](https://kubernetes.io/) cluster for testing purposes. The procedure detailed here was tested on a machine running Mac OSX with an Intel CPU, and adapts the instructions and examples referenced [here](https://docs.dagster.io/deployment/guides/kubernetes/deploying-with-helm).

## Further details

The testing environment is a three-node k8s cluster created using [KinD](https://kind.sigs.k8s.io/). One node runs the "control plane" (the KinD API, etc.), and two "worker" nodes run the dagster applications (a webserver, a scheduling daemon, a "user code" server, a postgres DB, and two celery workers with a local rabbitmq queue) as well as any tasks that get run as parts of dagster jobs.

The dagster deployment is customized from the default Helm chart in that it uses a CeleryK8sRunLauncher (instead of a K8sRunLauncher) to launch tasks so that each step in a job gets executed in its own Kubernetes pod. It also includes an additional persistent volume and claim tethered to the local file system to handle I/O for jobs (the example linked above puts output in an s3 bucket instead).

To briefly explain how the deployment works, Dagster loads one or more "user code" servers that are linked to Docker images (currently stored on the openmsi DockerHub org). Those Docker images must have Dagster installed (along with its dependencies for running in k8s), and must have baked into them (i.e. the files copied into them, or a corresponding package installed in them) some Python module that acts as a Dagster "code location" with definitions of assets, ops, jobs, graphs, resources, etc. 

The different Dagster components are installed in k8s, along with the "user code" server, and the webserver UI can be used to launch jobs (jobs can also be run on defined schedules if desired, or by running some "kubectl exec" commands in the dagster pods). Each step of each job is submitted to a celery queue backed by rabbit mq, and executed as a k8s Job. Logs are visible in the webserver UI, and output serialized/deserialized from tasks runs is saved to the local (off-cluster) disk (this is just one possible type of I/O management).

## Dependencies

Setting up this testing environment requires access to a few external tools. The first is [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/), for locally creating and managing containers and groups of containers. If you install [Docker Desktop](https://www.docker.com/products/docker-desktop/) you'll get access to both.

The second is [KinD](https://kind.sigs.k8s.io/), a tool for creating local Kubernetes clusters where the nodes are run in individual Docker containers. [Click here](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) to open the page on installing KinD, or, if you're on a Mac with [Homebrew](https://brew.sh/) installed, you can simply `brew install kind`.

Next you'll need an installation of the k8s command line tool, called "[kubectl](https://kubernetes.io/docs/reference/kubectl/)". If you have Docker Desktop installed, you can get access to kubectl by ticking the "Enable Kubernetes" box in Docker/Settings/Kubernetes. If you'd like to maintain more control over your local k8s functionality, though, you can install kubectl on its own by following the instructions [here](https://kubernetes.io/docs/tasks/tools/), or with `brew install kubectl`. Just know that you should only use *one* of these methods on your machine as they may conflict with one another. Homebrew may warn you of this if you install it that way.

Finally, you'll need to install [Helm](https://helm.sh/), the Kubernetes package manager. You can install the Helm CLI by following the instructions [here](https://helm.sh/docs/intro/install/), or again with `brew install helm`. With all of these tools installed, you're ready to clone this repository locally (or download the files in this folder) and follow the tutorial below. 

## Tutorial

### Build and push the "user code" Docker image

The [imqcam](../imqcam/) directory in this repository is set up as an example of a Dagster "code location" using the [Definitions API](https://docs.dagster.io/_apidocs/definitions) (check the [__init__.py](../imqcam/__init__.py) file for what those Definitions are). To get that code location loaded into Dagster in k8s we first need to make a Docker image from it (including the dependencies for running Dagster in k8s) and push that to a registry. Here we'll use the the Dockerfile in that folder to build the image, and we'll push it to the `openmsi` Dockerhub organization.

Build and push the Docker image with the baked-in user code:

    cd dagster_workflow/imqcam
    docker build -t openmsi/testing_k8s_dagster .
    docker login
    docker push openmsi/testing_k8s_dagster

### Set up the KinD cluster

With the code location available in a Docker registry, we can then create the KinD cluster from its .yaml definition file:

    cd dagster_workflow/local_k8s
    kind create cluster --name dagster-cluster --config kind-cluster.yaml

If you'd like, you can check that the cluster is running with:

    kubectl cluster-info
    kubectl get nodes -o wide

Next, create a namespace to install dagster in:

    kubectl create namespace dagster
    kubectl get namespaces

### Create the PVs and PVCs for local data storage and for the I/O manager to use

Dagster implements a number of different I/O managers that handle serializting and deserializing inputs and outputs between each of its tasks. The vanilla tutorial linked above uses an S3 bucket for this purpose, but I've edited the deployment to use a "[`FilesystemIOManager`](https://docs.dagster.io/_apidocs/io-managers#dagster.FilesystemIOManager)" instead, which I think is simpler. It also lets you see what the ser/des i/o looks like by storing it on your local system.

Creating the cluster above should have created two folders inside this one called "`imqcam_local_data`" and "`imqcam_filesystem_io`". The first is a location where you can put files that you'd like to be able to see from inside the system, and the second is the root for all of the managed I/O. We'll use a k8s yaml file to create Persistent Volumes and Persistent Volume Claims pointing to those folder; they'll be mounted at `/tmp/imqcam_local_data` and `/tmp/imqcam_filesystem_io_data`, respectively, inside every one of the Dagster pods in the cluster. 

Run:

    kubectl apply -f volumes_and_claims.yaml
    kubectl get pv -n dagster
    kubectl get pvc -n dagster

### Create secrets

Some important values needed by DAGs are stored as Kubernetes Secrets. Those Secrets are created by the "`secrets.yaml`" file in this directory, and their values are not committed directly to this repository. For that reason, you'll need to edit the `secrets.yaml` file by hand after you've cloned this repository. That file has some values in it that read like "`base_64_encoded_*`"; you should replace those values with the base64-encoded real values of the Secrets that you need to create. To base64-encode a particular string, you can run:

    echo -n "string_to_encode" | base64 -b 0

You should know what the values for each of the Secrets should be, and then you should base64 encode those string values and replace the "`base_64_encoded_*`" values in the `secrets.yaml` file. After that's done, you can create the Secrets and add them to the cluster with:

    kubectl apply -f secrets.yaml

And check that they exist with:

    kubectl get secrets -n dagster

### Install Dagster

We'll install Dagster in k8s using the Helm chart that Dagster makes publicly available. The [`values.yaml`](./values.yaml) file in this directory edits its default configurations to work as described above.

First, add the Dagster Helm chart repo:

    helm repo add dagster https://dagster-io.github.io/helm

Then install dagster referencing the custom `values.yaml` file:

    helm install dagster dagster/dagster -n dagster --values values.yaml --debug

And that's all! But while I'm here: if you'd like to see what the default values.yaml file looks like (helpful for figuring out how to edit it), you can get your own copy of it with:

    helm show values dagster/dagster > default_values.yaml

(There's already a copy in the repo).

### Interacting with Dagster

You can open up the Dagster webserver UI by forwarding the port out of its pod. First, get the name of the webserver pod by running:

    kubectl get pods -n dagster

And then forward the port with:

    kubectl -n dagster port-forward [dagster-webserver-pod-name] 8080:80

Then you can pull up [localhost:8080](http://localhost:8080/) to view the webserver.

One annoying thing is that Dagster doesn't automatically delete pods created for tasks that completed successfully, and it's up to the user to remove them every now and then. You can do that with:

    kubectl get pods -n dagster --field-selector=status.phase==Succeeded -o=name | xargs kubectl delete -n dagster

### Editing the install

When you make changes to the code location (anything inside the `imqcam` folder) you need to rebuild and push its Docker image, and then you need to restart the deployment for the code location server in k8s. Here's how to do that:

    cd dagster_workflow/imqcam
    docker build -t openmsi/testing_k8s_dagster . && docker login && docker push openmsi/testing_k8s_dagster
    kubectl rollout restart deployment dagster-dagster-user-deployments-imqcam-example-1 -n dagster

When that's done running you should be able to reload the code location from the UI (or it might happen automatically) to see your new code location's jobs, etc. If there's a bug in the code you may need to debug the pod running the code location server.

K8s installs themselves can also be adjusted without uninstalling/reinstalling everything. You can edit the `values.yaml` file however you'd like, and then edit a running installation with:

    helm upgrade -f values.yaml dagster dagster/dagster -n dagster --debug

K8s will figure out which pods need to be changed and it will remake them by itself without compromising the integrity of the overall installation.

### Clearing it all out

Uninstall dagster and delete the entire cluster with:

    helm uninstall dagster -n dagster
    kind delete cluster --name dagster-cluster
