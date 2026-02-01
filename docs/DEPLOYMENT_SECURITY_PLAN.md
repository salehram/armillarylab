# Database Credential Security - Deployment Plan

*Created: 2025-12-27 | Status: Planning Phase*

## Overview
This document outlines the plan for implementing secure database credential management across different deployment scenarios. The current implementation uses .env files for simplicity, but this plan provides a roadmap for more secure approaches.

## Current State (v2.0.0-dev)
- PostgreSQL credentials stored in `.env.production` file
- Simple environment variable loading via python-dotenv
- Works but not production-secure for sensitive deployments

## Target Deployment Scenarios

### 1. Local Development Deployments

#### A. Direct OS Terminal Execution
**Approach**: OS-level environment variables without .env files
```bash
# Windows
set DATABASE_TYPE=postgresql
set DATABASE_URL=postgresql://user:password@host/db
python app.py

# Linux/macOS  
export DATABASE_TYPE=postgresql
export DATABASE_URL=postgresql://user:password@host/db
python app.py
```
**Security Level**: Medium (credentials in shell history)
**Complexity**: Low
**Use Case**: Local development, testing

#### B. Docker Deployment
**Approach**: Environment variables passed to container
```bash
docker run -e DATABASE_TYPE=postgresql \
           -e DATABASE_URL=postgresql://user:password@host/db \
           astroplanner:latest
```
**Security Level**: Medium (visible in docker inspect)
**Complexity**: Low
**Use Case**: Local containerized testing, development environments

#### C. Local Kubernetes (minikube/kind)
**Approach**: Kubernetes Secrets
```yaml
# Create secret
kubectl create secret generic db-credentials \
  --from-literal=DATABASE_URL=postgresql://user:pass@host/db

# Reference in deployment
env:
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: db-credentials
      key: DATABASE_URL
```
**Security Level**: High (encrypted at rest)
**Complexity**: Medium
**Use Case**: Local K8s development, testing K8s deployments

### 2. Cloud Deployments (GCP Focus)

#### A. Cloud Run + Secret Manager
**Approach**: GCP Secret Manager integration
```bash
# Store in Secret Manager
gcloud secrets create db-connection-string \
  --data-file=<(echo "postgresql://user:pass@host/db")

# Deploy Cloud Run service
gcloud run deploy astroplanner \
  --image gcr.io/project/astroplanner \
  --update-secrets DATABASE_URL=db-connection-string:latest
```
**Security Level**: Very High (GCP managed encryption, IAM controls)
**Complexity**: Medium
**Use Case**: Production Cloud Run deployments

#### B. GKE + Secret Manager
**Approach**: GKE with Secret Manager CSI driver
```yaml
# Service Account with Secret Manager access
# SecretProviderClass for CSI driver
# Deployment mounting secrets as volumes
```
**Security Level**: Very High (GCP managed, workload identity)
**Complexity**: High
**Use Case**: Production GKE deployments, enterprise environments

## Implementation Phases

### Phase 1: Current State (DONE)
- ✅ Basic PostgreSQL support with .env files
- ✅ Working database abstraction layer
- ✅ CLI management tools
- ✅ Simple deployment examples

### Phase 2: OS Environment Variables (FUTURE)
**Goal**: Remove dependency on .env files for production
**Changes Needed**:
- Modify `config/database.py` to prioritize OS env vars over .env files
- Add warning when production credentials found in .env files  
- Create deployment scripts for each scenario
- Update documentation with security best practices

### Phase 3: Container Security (FUTURE)
**Goal**: Secure containerized deployments
**Changes Needed**:
- Docker Compose files without hardcoded credentials
- Kubernetes Secret templates
- Init container patterns for credential fetching
- Health check endpoints that don't expose credentials

### Phase 4: Cloud Integration (FUTURE)  
**Goal**: Production-ready cloud deployments
**Changes Needed**:
- GCP Secret Manager integration in application code
- Cloud Run deployment automation
- GKE manifests with Secret Manager CSI
- IAM roles and service accounts
- Monitoring and alerting for credential access

## Security Considerations by Scenario

### Development (Low Security Requirements)
- .env files acceptable for local development
- OS environment variables for CI/CD
- Clear separation between dev/prod credentials

### Staging (Medium Security Requirements)  
- No .env files in containers
- Kubernetes Secrets or equivalent
- Credential rotation capabilities
- Audit logging of credential access

### Production (High Security Requirements)
- Managed secret services (Secret Manager, Vault)
- Workload identity and service accounts
- Automatic credential rotation
- Comprehensive audit trails
- Network-level security (VPC, private endpoints)

## Migration Strategy

### Step 1: Backward Compatibility
- Keep existing .env support
- Add OS environment variable precedence
- Warn on insecure configurations

### Step 2: Deployment Templates
- Create secure deployment examples
- Provide migration tools/scripts
- Document security best practices

### Step 3: Cloud Integration
- Implement cloud provider integrations
- Add monitoring and alerting
- Automate credential management

## File Structure (Future)
```
astroplanner/
├── deploy/
│   ├── local/
│   │   ├── run-with-env.sh
│   │   ├── docker-compose.secure.yml
│   │   └── k8s-secrets.yml
│   ├── gcp/
│   │   ├── cloud-run/
│   │   │   ├── deploy.sh
│   │   │   └── service.yaml
│   │   └── gke/
│   │       ├── secret-manager-csi.yaml
│   │       └── deployment.yaml
│   └── README.md
├── config/
│   ├── database.py (enhanced)
│   └── secrets.py (new)
└── docs/
    ├── SECURITY.md
    └── DEPLOYMENT.md
```

## Decision Points for Implementation

1. **Environment Variable Precedence**: Should OS env vars always override .env files?
2. **Error Handling**: How to handle missing credentials gracefully?
3. **Development Experience**: How to maintain easy local development setup?
4. **Cloud Provider Support**: Start with GCP only or multi-cloud from start?
5. **Backward Compatibility**: Keep .env support permanently or deprecate?

## Notes
- This plan focuses on GCP as requested
- Each phase builds incrementally on previous phases
- Security increases with complexity - choose appropriate level for use case
- All approaches should maintain the same application code interface