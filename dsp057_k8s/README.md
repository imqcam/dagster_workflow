kubectl create namespace maggie-imqcam-dagster

kubectl create secret docker-registry regcred --docker-server=containers.repo.sciserver.org --docker-username=anonymous --docker-password=anonymous --docker-email=[your_docker_email] -n maggie-imqcam-dagster