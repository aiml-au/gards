# Deploying the Application with Helm and Terraform
Below are the step-by-step instructions for executing command-line operations within the terraform directory, which contains subdirectories named cluster, infrastructure, and app.

## Prerequisites 
Ensure the following prerequisites are installed locally before deployment.

- [Terraform](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)  
- [Helm](https://helm.sh/docs/intro/install/) 
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli#install)
- [Kubectl](https://kubernetes.io/docs/tasks/tools/) 
- [Kubefwd](https://kubefwd.com/install/)

# Deploying with Terraform

We currently store our terraform state in the aiml-dra-anomaly-data bucket on GCS. All other cloud resources will be deployed by Terraform to run on Azure.

1. Log in to gcloud
```shell
gcloud auth login
```

2. Log in to Azure
```shell
az login
```

3. Set subscription account
```shell
az account set --subscription "<SubscriptionId or SubscriptionName>"
```

4. Apply the cluster config: This stage configures storage container and a DNS zone, as well as sensitive information like certificates and keys.

Start from the terraform directory. 
```shell
cd cluster
terraform init
terraform plan -out plan
terraform apply plan
``` 

5. Apply the infrastructure config: This stage updates the infrastructure configurations including nats and ngnix.

Start from the terraform directory. 
```shell
cd infrastructure
terraform init
terraform plan -out plan
terraform apply plan
``` 

6. Configure kubectl to use the AKS Cluster
```shell
az aks get-credentials --resource-group dra --name dra
```

7. Start Kubefwd to get access to the NATS server.
```shell
sudo -E kubefwd svc -n nats
```

8. Apply the app config: This stage applies the app configurations, deploying set of resources within the Kubernetes Cluster. 

Start from the terraform directory. 
```shell
cd app
terraform init
terraform plan -out plan
terraform apply plan
```

9. Configure DNS to point to the Azure Cloud K8s Cluster Endpoint by updating DNS record on Google Cloud (need to be set by AIML Infrastructure Admin).

The application can then be accessed at https://dra.az.aiml.team/

## Verifying Deployment

To verify all resources were deployed, you can verify from 'Resources' in Azure Portal or by using kubectl to retrieve resource information

1. Verify connection to cluster
```shell
kubectl cluster-info
```
2. Check deployed resources
```shell
kubectl get deployments --all-namespaces
```

3. Get all pods and ensure all pods are running
```shell
kubectl get pods --all-namespaces
```

4. Get ingress and ensure host and address are defined 
```shell
kubectl get ingress --all-namespaces
```

5. Check application access through svc and ensure there is external-ip for accessing the web application
```shell
kubectl get svc -n app
```

6. Test the live application by going to https://dra.az.aiml.team/

## Destroying the cluster

If you need to tear down the cluster, run `terraform destroy` in the reverse order:

1. Destroy cluster

Start from the terraform directory. 
```shell
cd app
terraform destroy
cd ../infrastructure
terraform destroy
cd ../cluster
terraform destroy
```
