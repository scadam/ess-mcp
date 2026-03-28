#!/usr/bin/env bash
# ===========================================================================
#  ESS-MCP  –  Single-click Azure deployment
#
#  Deploys the MCP servers to Azure Container Apps from scratch.
#  Assumes only an active Azure subscription exists.
#
#  Usage:
#    ./deploy.sh                         # Deploy ALL servers
#    ./deploy.sh --servers workday,jira  # Deploy specific servers
#    ./deploy.sh --servers workday       # Deploy a single server
#    ./deploy.sh --help                  # Show help
#
#  Prerequisites:
#    - Azure CLI (az) installed and logged in
#    - Docker (or Podman) installed and running
#    - Bash 4+
# ===========================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BICEP_FILE="${SCRIPT_DIR}/main.bicep"

DEFAULT_LOCATION="eastus"
DEFAULT_BASE_NAME="essmcp"
DEFAULT_SERVERS="all"
DEFAULT_IMAGE_TAG="latest"
DEFAULT_CPU="0.5"
DEFAULT_MEMORY="1Gi"
DEFAULT_MIN_REPLICAS=0
DEFAULT_MAX_REPLICAS=3

VALID_SERVERS=("workday" "servicenow" "salesforce" "jira")

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Colour

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { printf "${BLUE}ℹ ${NC}%s\n" "$*"; }
ok()    { printf "${GREEN}✔ ${NC}%s\n" "$*"; }
warn()  { printf "${YELLOW}⚠ ${NC}%s\n" "$*"; }
err()   { printf "${RED}✖ ${NC}%s\n" "$*" >&2; }
header(){ printf "\n${CYAN}━━━ %s ━━━${NC}\n\n" "$*"; }

usage() {
    cat <<EOF
${CYAN}ESS-MCP Azure Deployment${NC}

Deploy one, several, or all MCP servers to Azure Container Apps.

${YELLOW}Usage:${NC}
  $(basename "$0") [OPTIONS]

${YELLOW}Options:${NC}
  -s, --servers SERVERS   Comma-separated list of servers to deploy.
                          Valid: workday, servicenow, salesforce, jira, all
                          (default: all)
  -l, --location LOC      Azure region (default: ${DEFAULT_LOCATION})
  -n, --name NAME         Base name for resources, 3-16 chars
                          (default: ${DEFAULT_BASE_NAME})
  -t, --tag TAG           Docker image tag (default: ${DEFAULT_IMAGE_TAG})
      --cpu CPU           CPU cores per container (default: ${DEFAULT_CPU})
      --memory MEM        Memory per container (default: ${DEFAULT_MEMORY})
      --min-replicas N    Minimum replicas (default: ${DEFAULT_MIN_REPLICAS})
      --max-replicas N    Maximum replicas (default: ${DEFAULT_MAX_REPLICAS})
  -e, --env-file FILE     Path to .env file with service configuration
      --resource-group RG Existing resource group name (skip creation)
      --subscription SUB  Azure subscription ID or name
      --dry-run           Show what would be deployed without executing
  -h, --help              Show this help message

${YELLOW}Examples:${NC}
  $(basename "$0")                                    # Deploy all servers
  $(basename "$0") --servers workday                  # Deploy Workday only
  $(basename "$0") --servers workday,jira --name myapp  # Deploy two servers
  $(basename "$0") --env-file ./my-config.env         # Use env file for config
  $(basename "$0") --location westeurope              # Deploy to West Europe

EOF
    exit 0
}

validate_servers() {
    local input="$1"
    if [[ "${input}" == "all" ]]; then
        return 0
    fi
    IFS=',' read -ra parts <<< "${input}"
    for s in "${parts[@]}"; do
        s="$(echo "${s}" | xargs)"  # trim whitespace
        local found=false
        for v in "${VALID_SERVERS[@]}"; do
            if [[ "${s}" == "${v}" ]]; then
                found=true
                break
            fi
        done
        if [[ "${found}" == "false" ]]; then
            err "Unknown server: '${s}'. Valid servers: ${VALID_SERVERS[*]}"
            exit 1
        fi
    done
}

check_prerequisites() {
    header "Checking prerequisites"

    if ! command -v az &>/dev/null; then
        err "Azure CLI (az) is not installed."
        info "Install: https://learn.microsoft.com/cli/azure/install-azure-cli"
        exit 1
    fi
    ok "Azure CLI found: $(az version --query '"azure-cli"' -o tsv 2>/dev/null || echo 'unknown')"

    if ! az account show &>/dev/null; then
        err "Not logged in to Azure. Run: az login"
        exit 1
    fi
    ok "Azure CLI authenticated"

    if command -v docker &>/dev/null; then
        CONTAINER_ENGINE="docker"
        ok "Docker found"
    elif command -v podman &>/dev/null; then
        CONTAINER_ENGINE="podman"
        ok "Podman found"
    else
        err "Docker or Podman is required but not installed."
        exit 1
    fi

    if [[ ! -f "${BICEP_FILE}" ]]; then
        err "Bicep template not found: ${BICEP_FILE}"
        exit 1
    fi
    ok "Bicep template found"

    if [[ ! -f "${REPO_ROOT}/mcp_servers/Dockerfile" ]]; then
        err "Dockerfile not found: ${REPO_ROOT}/mcp_servers/Dockerfile"
        exit 1
    fi
    ok "Dockerfile found"
}

load_env_file() {
    local env_file="$1"
    if [[ ! -f "${env_file}" ]]; then
        err "Environment file not found: ${env_file}"
        exit 1
    fi
    info "Loading environment variables from: ${env_file}"
    local env_vars_json="["
    local first=true
    while IFS= read -r line || [[ -n "${line}" ]]; do
        # Skip comments and empty lines
        line="$(echo "${line}" | xargs)"
        if [[ -z "${line}" || "${line}" == \#* ]]; then
            continue
        fi
        local key="${line%%=*}"
        local val="${line#*=}"
        if [[ "${first}" == "true" ]]; then
            first=false
        else
            env_vars_json+=","
        fi
        env_vars_json+="{\"name\":\"${key}\",\"value\":\"${val}\"}"
    done < "${env_file}"
    env_vars_json+="]"
    echo "${env_vars_json}"
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
SERVERS="${DEFAULT_SERVERS}"
LOCATION="${DEFAULT_LOCATION}"
BASE_NAME="${DEFAULT_BASE_NAME}"
IMAGE_TAG="${DEFAULT_IMAGE_TAG}"
CPU="${DEFAULT_CPU}"
MEMORY="${DEFAULT_MEMORY}"
MIN_REPLICAS="${DEFAULT_MIN_REPLICAS}"
MAX_REPLICAS="${DEFAULT_MAX_REPLICAS}"
ENV_FILE=""
RESOURCE_GROUP=""
SUBSCRIPTION=""
DRY_RUN=false
CONTAINER_ENGINE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -s|--servers)      SERVERS="$2"; shift 2 ;;
        -l|--location)     LOCATION="$2"; shift 2 ;;
        -n|--name)         BASE_NAME="$2"; shift 2 ;;
        -t|--tag)          IMAGE_TAG="$2"; shift 2 ;;
        --cpu)             CPU="$2"; shift 2 ;;
        --memory)          MEMORY="$2"; shift 2 ;;
        --min-replicas)    MIN_REPLICAS="$2"; shift 2 ;;
        --max-replicas)    MAX_REPLICAS="$2"; shift 2 ;;
        -e|--env-file)     ENV_FILE="$2"; shift 2 ;;
        --resource-group)  RESOURCE_GROUP="$2"; shift 2 ;;
        --subscription)    SUBSCRIPTION="$2"; shift 2 ;;
        --dry-run)         DRY_RUN=true; shift ;;
        -h|--help)         usage ;;
        *)                 err "Unknown option: $1"; usage ;;
    esac
done

# Validate
validate_servers "${SERVERS}"

if [[ ${#BASE_NAME} -lt 3 || ${#BASE_NAME} -gt 16 ]]; then
    err "Base name must be 3-16 characters. Got: '${BASE_NAME}' (${#BASE_NAME} chars)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Main deployment
# ---------------------------------------------------------------------------
main() {
    header "ESS-MCP Azure Deployment"

    info "Servers:     ${SERVERS}"
    info "Location:    ${LOCATION}"
    info "Base name:   ${BASE_NAME}"
    info "Image tag:   ${IMAGE_TAG}"
    info "CPU/Memory:  ${CPU} / ${MEMORY}"
    info "Replicas:    ${MIN_REPLICAS}-${MAX_REPLICAS}"

    if [[ -n "${SUBSCRIPTION}" ]]; then
        info "Subscription: ${SUBSCRIPTION}"
    fi

    check_prerequisites

    # ── Set subscription ──────────────────────────────────────────────
    if [[ -n "${SUBSCRIPTION}" ]]; then
        header "Setting Azure subscription"
        az account set --subscription "${SUBSCRIPTION}"
        ok "Subscription set to: ${SUBSCRIPTION}"
    fi

    local sub_name
    sub_name="$(az account show --query 'name' -o tsv)"
    local sub_id
    sub_id="$(az account show --query 'id' -o tsv)"
    info "Using subscription: ${sub_name} (${sub_id})"

    # ── Resource group ────────────────────────────────────────────────
    local rg="${RESOURCE_GROUP:-${BASE_NAME}-rg}"
    header "Resource Group: ${rg}"

    if az group show --name "${rg}" &>/dev/null; then
        ok "Resource group '${rg}' already exists"
    else
        if [[ "${DRY_RUN}" == "true" ]]; then
            info "[DRY RUN] Would create resource group '${rg}' in '${LOCATION}'"
        else
            info "Creating resource group '${rg}' in '${LOCATION}'..."
            az group create --name "${rg}" --location "${LOCATION}" --output none
            ok "Resource group created"
        fi
    fi

    # ── Build & push Docker image ─────────────────────────────────────
    header "Building Docker image"

    if [[ "${DRY_RUN}" == "true" ]]; then
        info "[DRY RUN] Would build image from ${REPO_ROOT}/mcp_servers"
        info "[DRY RUN] Would deploy Bicep template with servers=${SERVERS}"
        header "Dry run complete"
        exit 0
    fi

    # Deploy Bicep first to get the ACR name
    header "Deploying Azure infrastructure (Bicep)"

    # Build env vars JSON
    local env_vars_param="[]"
    if [[ -n "${ENV_FILE}" ]]; then
        env_vars_param="$(load_env_file "${ENV_FILE}")"
    fi

    info "Deploying infrastructure (ACR, Log Analytics, Container App Environment)..."
    local deploy_output
    deploy_output="$(az deployment group create \
        --resource-group "${rg}" \
        --template-file "${BICEP_FILE}" \
        --parameters \
            baseName="${BASE_NAME}" \
            servers="${SERVERS}" \
            imageTag="${IMAGE_TAG}" \
            cpu="${CPU}" \
            memory="${MEMORY}" \
            minReplicas="${MIN_REPLICAS}" \
            maxReplicas="${MAX_REPLICAS}" \
            envVars="${env_vars_param}" \
        --query 'properties.outputs' \
        -o json 2>&1)" || {
            # First deployment may fail because the image doesn't exist yet in ACR.
            # Extract ACR name and push the image, then re-deploy.
            warn "Initial deployment expected to need image push first. Continuing..."
        }

    # Get ACR details
    local acr_name
    acr_name="$(echo "${deploy_output}" | jq -r '.acrName.value // empty' 2>/dev/null || true)"

    if [[ -z "${acr_name}" ]]; then
        # ACR may have been created even if container app failed; find it
        acr_name="$(az acr list --resource-group "${rg}" --query '[0].name' -o tsv 2>/dev/null || true)"
    fi

    if [[ -z "${acr_name}" ]]; then
        err "Could not determine ACR name. Check deployment logs."
        exit 1
    fi

    local acr_server
    acr_server="$(az acr show --name "${acr_name}" --query 'loginServer' -o tsv)"
    ok "Container Registry: ${acr_server}"

    # Login to ACR
    info "Logging in to ACR..."
    az acr login --name "${acr_name}"
    ok "ACR login successful"

    # Build and push image
    local full_image="${acr_server}/ess-mcp:${IMAGE_TAG}"
    info "Building image: ${full_image}"
    ${CONTAINER_ENGINE} build \
        -t "${full_image}" \
        -f "${REPO_ROOT}/mcp_servers/Dockerfile" \
        "${REPO_ROOT}/mcp_servers"
    ok "Image built"

    info "Pushing image to ACR..."
    ${CONTAINER_ENGINE} push "${full_image}"
    ok "Image pushed: ${full_image}"

    # ── Re-deploy with the image now available ────────────────────────
    header "Deploying Container Apps"

    info "Deploying Container Apps with image: ${full_image}"
    deploy_output="$(az deployment group create \
        --resource-group "${rg}" \
        --template-file "${BICEP_FILE}" \
        --parameters \
            baseName="${BASE_NAME}" \
            servers="${SERVERS}" \
            imageTag="${IMAGE_TAG}" \
            cpu="${CPU}" \
            memory="${MEMORY}" \
            minReplicas="${MIN_REPLICAS}" \
            maxReplicas="${MAX_REPLICAS}" \
            envVars="${env_vars_param}" \
        --query 'properties.outputs' \
        -o json)"

    ok "Deployment complete"

    # ── Print results ─────────────────────────────────────────────────
    header "Deployment Summary"

    echo "${deploy_output}" | jq -r '
        .containerAppFqdns.value[] |
        "  \(.server):",
        "    MCP:    \(.mcpEndpoint)",
        "    SSE:    \(.sseEndpoint)",
        "    Health: \(.healthEndpoint)",
        ""
    ' 2>/dev/null || warn "Could not parse deployment outputs"

    ok "All MCP servers deployed successfully!"
    echo ""
    info "To view logs:  az containerapp logs show --name ${BASE_NAME}-<server> --resource-group ${rg}"
    info "To delete all: az group delete --name ${rg} --yes --no-wait"
    echo ""
}

main
