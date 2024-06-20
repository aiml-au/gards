#!/bin/bash

# Script Name: deploy_resources.sh
# Description: This script automates the deployment of specified resources to a Kubernetes cluster. It ensures a consistent and repeatable deployment process by applying configuration files or templates to the cluster.
# Prerequisites:
# - Kubernetes CLI (kubectl) must be installed and configured to communicate with your cluster.
# - User executing the script must have the necessary permissions to deploy resources to the cluster.
# - Any environment-specific variables or secrets should be set prior to running this script.
# - All Docker containers used by this script must be previously built and pushed to docker.aiml.team
# Usage:
# 1. Make the script executable: chmod +x deploy_resources.sh
# 2. Run the script: ./deploy_resources.sh


echo "*** Deploying FRP server on GKE to forward request ***"

# set GKE Kubernetes cluster and namespace
kubectl config use-context gke_aiml-infrastructure_australia-southeast1-b_aiml-infrastructure-cluster --namespace=aiml-dra-anomaly

# create config map
kubectl create configmap frps-config --from-file=frps.toml

# apply
kubectl apply -f gke-deploy.k8s.yaml

kubectl wait --for=condition=ready pod -l app=frp-dra-service --timeout=1200s

if [ $? -eq 0 ]; then

    echo "*** The following deployment was created ***"
    kubectl get deployment


    echo "*** Deploying DRA services on DPC ***"

    # set DPC Kubernetes cluster and namespace
    kubectl config use-context dpc --namespace=aiml-dra-anomaly


    # create config map
    kubectl create configmap nats-config --from-file=../queue/config/
    kubectl create configmap postgres-config --from-file=../db/config/
    kubectl create configmap nats-init --from-file=../queue/init/
    kubectl create configmap frpc-config --from-file=frpc.toml

    # apply
    kubectl apply -f dpc-deploy.k8s.yaml


    echo "*** The following statefulsets were created ***"
    kubectl get statefulset

    echo "*** The following job was created ***"
    kubectl get statefulset

    echo "*** The following pods were deployed ***"
    kubectl get pods

    echo "*** The following pvcs were deployed ***"
    kubectl get pvc

    echo "*** The following svcs were deployed ***"
    kubectl get svc
else
    echo "FRP server deployment took longer than expected"
fi

