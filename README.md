# The AI_INFN Platform Helm Chart

## Documentation and installation walkthrough
Temporarily here: https://codimd.infn.it/s/5X0AHJYhz


## Minimal `values.yaml`:
The Helm Chart will generate tokens and secrets for internal communication, but you 
need to provide your own tokens and authentications for accessing external services.

In addition, you should generate and store deployement-unique tokens that should not 
be regenerated upon uninstalling and reinstalling the chart.

```yaml
hostname: # Put here the hostname of your setup, e.g. "jhub.123.45.67.89.myip.cloud.infn.it"

bastionAdminPublicKey: # Put here a public RSA key for accessing the bastion as administrator
                       # You may have one in your `$HOME/.ssh/id_rsa.pub`, 
                       # otherwise run `ssh-keygen` to generate

# juicefsMetaUrl is the url to the metadata backend (redis or PostgreSQL)
juicefsMetaUrl: <URL to a valid metadata backend>

# juicefsBucket is the url to the bucket where to store jfs data
juicefsBucket: <URL to a valid S3 bucket>

# juicefsAccessKey is the access key of the object storage
juicefsAccessKey: <Access Key for the storage bucket>

# juicefsSecretKey is the secret key of the object storage
juicefsSecretKey: <Secret Key for the storage bucket>

jhubIamClientId: # Put here the id of a client on iam.cloud.infn.it
jhubIamClientSecret: # Put here the secret of your client
jhubCryptKey: # Generate and copy here a deployment-unique token: `openssl rand -hex 32`
jhubMetricApiKey:  # Generate and copy here a deployment-unique token: `openssl rand -hex 32`

dashboardFlaskSecret: # Generate and copy here a deployment-unique token: `openssl rand -hex 32`

jupyterhub:
  proxy:
    secretToken: # Generate and copy here a deployment-unique token: `openssl rand -hex 32`

  hub:
    cookieSecret: # Generate and copy here a deployment-unique token: `openssl rand -hex 32`
```

