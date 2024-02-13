# Testing Dagster deployment with a local Kubernetes cluster

I'm working on getting a Dagster deployment running in a local k8s cluster by adapting the instructions [here](https://docs.dagster.io/deployment/guides/kubernetes/deploying-with-helm).

## Further details

## Dependencies

## Tutorial

Build and push the Docker image with the baked-in user code:

    cd dagster_workflow/imqcam
    docker build -t openmsi/testing_k8s_dagster .
    docker login
    docker push openmsi/testing_k8s_dagster

Create the KinD cluster from its .yaml definition file

    cd dagster_workflow/local_k8s
    kind create cluster --name dagster-cluster --config kind-cluster.yaml

Check that the cluster is running with:

    kubectl cluster-info
    kubectl get nodes -o wide

Create a namespace to install dagster in:

    kubectl create namespace dagster
    kubectl get namespaces

Add the Dagster Helm chart repo:

    helm repo add dagster https://dagster-io.github.io/helm

Install dagster:

    helm install dagster dagster/dagster -n dagster --values values.yaml --debug

Open the webserver:

    # Get the name of the webserver pod
    kubectl get pods -n dagster
    kubectl -n dagster port-forward [dagster-webserver-pod-name] 8080:80

And then pull up [localhost:8080](http://localhost:8080/)

To get the default Helm values file for dagster:

    helm show values dagster/dagster > default_values.yaml

To edit an existing installation:

    helm upgrade -f values.yaml dagster dagster/dagster -n dagster --debug

Uninstall dagster and delete the entire cluster with:

    helm uninstall dagster -n dagster
    kind delete cluster --name dagster-cluster
