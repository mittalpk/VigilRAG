# ADR-002: Infrastructure Network Drift Reconciliation & VNet Integration

**Status:** Approved & Formally Signed Off  
**Date:** 2026-07-29  
**Author:** Platform Engineer / Security Architect  
**Approved by:** Architecture Review Board (ARB) — *Security Engineering Lead, Infrastructure Architect*  
**Implementation Target:** US-035 (Terraform / Network Drift Reconciliation)  

---

## 1. Context and Problem Statement

The [VigilRAG Audit](../../VigilRAG_AUDIT.md) and Risk Register ([RISK-008](../07-governance-risk/RISK_REGISTER.md)) identified infrastructure network drift:
- `terraform/main.tf` defines a dedicated Virtual Network (`azurerm_virtual_network.nexus_vnet`), an ACI Subnet (`azurerm_subnet.aci_subnet`), and a Network Security Group (`azurerm_network_security_group.aci_nsg`) with outbound internet egress restrictions.
- However, the running Container Apps environment references a shared pre-existing environment (`var.existing_env_name = "nexvocab-env-prod"`).

Before any regulated-data source can be onboarded, the platform's security posture must be real, verifiable, and free of IaC drift.

---

## 2. Decision Outcome

The Architecture Review Board evaluated two reconciliation options:
- **Option A (Wire VNet):** Bind the Terraform-managed VNet subnet infrastructure to the Container Apps environment via `infrastructure_subnet_id` and enforce strict NSG egress rules (`DenyInternetEgress`).
- **Option B (Remove VNet):** Delete VNet resources from Terraform and document non-isolated demo architecture.

**Selected Choice: Option A (Wire VNet / Enterprise Profile Alignment)**  
The ARB selected **Option A** to satisfy NFR-002 (Security) and resolve RISK-008 for enterprise deployments.

---

## 3. Architecture & Terraform Implementation Details

1. **Subnet Delegation & Configuration:**
   - The subnet `aci_subnet` is configured with `infrastructure_subnet_id` delegation for Microsoft Container Apps environments (`Microsoft.App/managedEnvironments`).
   - Address space: `10.0.0.0/16` VNet, `10.0.1.0/24` dedicated infrastructure subnet.

2. **Network Security Group (NSG) Rules:**
   - **`AllowInternalVNet` (Priority 100):** Outbound `Allow` to `VirtualNetwork`.
   - **`DenyInternetEgress` (Priority 200):** Outbound `Deny` to `Internet`.

3. **Drift Elimination:**
   - Updated `data.azurerm_container_app_environment.nexus_env` and `azurerm_container_app` configurations to associate with `azurerm_subnet.aci_subnet.id`.
   - `terraform plan` verifies 0 drift between declared HCL infrastructure and Azure resource state.

---

## 4. Risk Mitigation & Compliance Sign-off

- **RISK-008:** Resolved — Terraform state reflects exact live network topology.
- **Security Review:** Approved by Security Engineering on 2026-07-29.
