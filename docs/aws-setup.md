# AWS Setup for South China Sea Conflict Wargame

All WarMatrix execution runs on AWS. This keeps the local machine free and ensures the game is reproducible on a known environment.

## Provisioning

```bash
# From your local machine with AWS SSO configured:
aws --profile DeveloperAccess-565601887068 ec2 run-instances \
  --image-id ami-0fa5967347d08d2df \
  --instance-type r6a.4xlarge \
  --subnet-id subnet-02cc6ab34f2e1d217 \
  --security-group-ids sg-0b415461cf31b8dee \
  --iam-instance-profile Name=default-instance-role-with-ssm-access \
  --key-name octavian_aws_sept26 \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=200,VolumeType=gp3,DeleteOnTermination=true}' \
  --metadata-options 'HttpTokens=required,HttpEndpoint=enabled' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=wm-staff-agents}]' \
  --region us-east-1
```

Access via SSM (no public IP):

```bash
ssh i-04b7b4bfbf90df4c4  # uses ~/.ssh/config ProxyCommand for SSM
```

## Box setup

```bash
# As root:
apt-get update && apt-get install -y podman zstd jq git curl ca-certificates \
  uidmap slirp4netns fuse-overlayfs unzip nfs-common rsync python3-pip
loginctl enable-linger ubuntu

# As ubuntu:
# Clone and set up
git clone https://github.com/CodeMetalAI/wm-staff-agents.git
git clone https://github.com/CodeMetalAI/WarMatrix.git
git clone https://github.com/CodeMetalAI/warmatrix-mcp.git
cd wm-staff-agents && uv sync --locked

# WarMatrix via docker compose (or podman)
cd ~/WarMatrix && docker compose up -d

# Configure env
cp ~/wm-staff-agents/.env.example ~/wm-staff-agents/.env
# Edit .env with WM_API_URL, WM_BEARER_TOKEN, OPENAI_API_KEY, etc.

# Run game
cd ~/wm-staff-agents
uv run python -m wm_staff_agents.cli run --turns 6 --warmatrix
uv run python -m wm_staff_agents.cli serve --host 0.0.0.0 --port 8080
```

## Stopping

```bash
aws --profile DeveloperAccess-565601887068 ec2 stop-instances --instance-ids i-04b7b4bfbf90df4c4 --region us-east-1
aws --profile DeveloperAccess-565601887068 ec2 terminate-instances --instance-ids i-04b7b4bfbf90df4c4 --region us-east-1
```
