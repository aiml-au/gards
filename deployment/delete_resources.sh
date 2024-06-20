#!/bin/bash

# Script Name: delete_resources.sh
# Description: This script automates the deletion of specified resources to a Kubernetes cluster. It ensures a consistent and repeatable deployment deletion process based on configuration files or templates to the cluster.
# Prerequisites:
# - Access to Kubernetes CLI (kubectl) where the application is deployed.
# - User executing the script must have the necessary permissions to delete resources from the cluster.
# Usage:
# 1. Make the script executable: chmod +x delete_resources.sh
# 2. Run the script: ./delete_resources.sh


# set dpc Kubernetes cluster and namespace
kubectl config use-context dpc --namespace=aiml-dra-anomaly
kubectl delete -f dpc-deploy.k8s.yaml

# delete config maps
kubectl delete configmap nats-config 
kubectl delete configmap postgres-config
kubectl delete configmap nats-init
kubectl delete configmap frpc-config

# set GKE Kubernetes cluster and namespace
kubectl config use-context gke_aiml-infrastructure_australia-southeast1-b_aiml-infrastructure-cluster --namespace=aiml-dra-anomaly

# delete
kubectl delete -f gke-deploy.k8s.yaml

# create config map
kubectl delete configmap frps-config

