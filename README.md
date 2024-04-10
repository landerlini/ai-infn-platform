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


# if you prefer disabling juicefs, issue juicefsEnabled: False instead of the following lines
juicefsBucket: <URL to a valid S3 bucket>
juicefsAccessKey: <Access Key for the storage bucket>
juicefsSecretKey: <Secret Key for the storage bucket>
juicefsMetaAuthToken: # Generate and copy here a deployment-unique token: `openssl rand -hex 32`


jhubIamClientId:      # Put here the id of a client on iam.cloud.infn.it
jhubIamClientSecret:  # Put here the secret of your client
jhubCryptKey:         # Generate and copy here a deployment-unique token: `openssl rand -hex 32`
jhubMetricApiKey:     # Generate and copy here a deployment-unique token: `openssl rand -hex 32`

dashboardFlaskSecret: # Generate and copy here a deployment-unique token: `openssl rand -hex 32`

jupyterhub:
  proxy:
    secretToken:      # Generate and copy here a deployment-unique token: `openssl rand -hex 32`

  hub:
    cookieSecret:     # Generate and copy here a deployment-unique token: `openssl rand -hex 32`
```

