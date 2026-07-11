param(
  [string]$TerraformDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

function Get-RequiredCommand {
  param(
    [string]$Name
  )

  $command = Get-Command $Name -ErrorAction SilentlyContinue

  if (-not $command) {
    throw "Required command '$Name' was not found in PATH."
  }

  return $command
}

function Get-TerraformOutputRaw {
  param(
    [string]$Name
  )

  $output = & terraform "-chdir=$TerraformDir" output -raw $Name

  if ($LASTEXITCODE -ne 0) {
    throw "Failed to read Terraform output '$Name'."
  }

  return ($output | Out-String).Trim()
}

function Get-TerraformOutputJson {
  param(
    [string]$Name
  )

  $output = & terraform "-chdir=$TerraformDir" output -json $Name

  if ($LASTEXITCODE -ne 0) {
    throw "Failed to read Terraform output '$Name'."
  }

  return ($output | Out-String | ConvertFrom-Json)
}

function Get-TerraformStateJson {
  $output = & terraform "-chdir=$TerraformDir" state pull

  if ($LASTEXITCODE -ne 0) {
    throw "Failed to read Terraform state."
  }

  return ($output | Out-String | ConvertFrom-Json)
}

function Get-TerraformConsoleString {
  param(
    [string]$Expression
  )

  Push-Location $TerraformDir

  try {
    $output = $Expression | terraform console

    if ($LASTEXITCODE -ne 0) {
      throw "Failed to evaluate Terraform console expression '$Expression'."
    }

    return ($output | Out-String).Trim()
  }
  finally {
    Pop-Location
  }
}

function Get-ExpectedEcrRepositoryNames {
  $encodedMap = Get-TerraformConsoleString -Expression "jsonencode(var.ecr_repository_names)"
  $decodedMap = $encodedMap | ConvertFrom-Json
  $repositoryMap = $decodedMap | ConvertFrom-Json

  return @($repositoryMap.PSObject.Properties | ForEach-Object { [string]$_.Value })
}

function Get-EcrRepositoriesFromState {
  $state = Get-TerraformStateJson
  $repositories = @()

  foreach ($resource in @($state.resources)) {
    if ($resource.type -ne "aws_ecr_repository" -or $resource.name -ne "application") {
      continue
    }

    foreach ($instance in @($resource.instances)) {
      $attributes = $instance.attributes

      if (-not $attributes.name -or -not $attributes.repository_url) {
        continue
      }

      $repositories += [pscustomobject]@{
        Name = [string]$attributes.name
        Uri  = [string]$attributes.repository_url
      }
    }
  }

  if ($repositories.Count -eq 0) {
    throw "No aws_ecr_repository.application instances were found in Terraform state."
  }

  return $repositories
}

function Invoke-AwsJson {
  param(
    [string[]]$Arguments
  )

  $output = & aws @Arguments --output json
  return ($output | Out-String | ConvertFrom-Json)
}

function Add-Success {
  param(
    [string]$Message
  )

  Write-Host "[ok] $Message" -ForegroundColor Green
}

function Add-Failure {
  param(
    [System.Collections.Generic.List[string]]$Failures,
    [string]$Message
  )

  $Failures.Add($Message) | Out-Null
  Write-Host "[fail] $Message" -ForegroundColor Red
}

Get-RequiredCommand -Name "terraform" | Out-Null
Get-RequiredCommand -Name "aws" | Out-Null

if (-not (Test-Path -Path (Join-Path $TerraformDir "terraform.tfstate"))) {
  throw "No terraform state file was found under '$TerraformDir'. Run terraform apply first."
}

$failures = New-Object 'System.Collections.Generic.List[string]'

$region = Get-TerraformOutputRaw -Name "aws_region"
$clusterName = Get-TerraformOutputRaw -Name "cluster_name"
$expectedAccountId = Get-TerraformOutputRaw -Name "aws_account_id"
$expectedRepositoryNames = Get-ExpectedEcrRepositoryNames
$repositories = Get-EcrRepositoriesFromState
$repositoriesByName = @{}

foreach ($repository in $repositories) {
  $repositoriesByName[$repository.Name] = $repository.Uri
}

$callerIdentity = Invoke-AwsJson -Arguments @("sts", "get-caller-identity")

if ($callerIdentity.Account -eq $expectedAccountId) {
  Add-Success "AWS CLI is authenticated to account $($callerIdentity.Account)."
} else {
  Add-Failure -Failures $failures -Message "AWS CLI account '$($callerIdentity.Account)' does not match Terraform output '$expectedAccountId'."
}

$clusterResponse = Invoke-AwsJson -Arguments @("eks", "describe-cluster", "--name", $clusterName, "--region", $region)
$cluster = $clusterResponse.cluster

if ($cluster.status -eq "ACTIVE") {
  Add-Success "EKS cluster '$clusterName' is ACTIVE."
} else {
  Add-Failure -Failures $failures -Message "EKS cluster '$clusterName' status is '$($cluster.status)', expected 'ACTIVE'."
}

$vpcId = $cluster.resourcesVpcConfig.vpcId
$subnetIds = @($cluster.resourcesVpcConfig.subnetIds)

$vpcResponse = Invoke-AwsJson -Arguments @("ec2", "describe-vpcs", "--vpc-ids", $vpcId, "--region", $region)

if (@($vpcResponse.Vpcs).Count -eq 1) {
  Add-Success "VPC '$vpcId' exists."
} else {
  Add-Failure -Failures $failures -Message "Expected VPC '$vpcId' to exist."
}

$subnetResponse = Invoke-AwsJson -Arguments (@("ec2", "describe-subnets", "--region", $region, "--subnet-ids") + $subnetIds)

if (@($subnetResponse.Subnets).Count -eq $subnetIds.Count) {
  Add-Success "All cluster subnets exist in AWS."
} else {
  Add-Failure -Failures $failures -Message "Expected $($subnetIds.Count) cluster subnets, found $(@($subnetResponse.Subnets).Count)."
}

$natResponse = Invoke-AwsJson -Arguments @("ec2", "describe-nat-gateways", "--region", $region, "--filter", "Name=vpc-id,Values=$vpcId", "Name=state,Values=available")

if (@($natResponse.NatGateways).Count -ge 1) {
  Add-Success "At least one NAT gateway is available in VPC '$vpcId'."
} else {
  Add-Failure -Failures $failures -Message "No available NAT gateways were found in VPC '$vpcId'."
}

$nodeGroupResponse = Invoke-AwsJson -Arguments @("eks", "list-nodegroups", "--cluster-name", $clusterName, "--region", $region)
$nodeGroupNames = @($nodeGroupResponse.nodegroups)

if ($nodeGroupNames.Count -eq 0) {
  Add-Failure -Failures $failures -Message "No managed node groups were found for cluster '$clusterName'."
}

foreach ($nodeGroupName in $nodeGroupNames) {
  $nodeGroup = (Invoke-AwsJson -Arguments @("eks", "describe-nodegroup", "--cluster-name", $clusterName, "--nodegroup-name", $nodeGroupName, "--region", $region)).nodegroup

  if ($nodeGroup.status -eq "ACTIVE") {
    Add-Success "Node group '$nodeGroupName' is ACTIVE."
  } else {
    Add-Failure -Failures $failures -Message "Node group '$nodeGroupName' status is '$($nodeGroup.status)', expected 'ACTIVE'."
  }
}

foreach ($repositoryName in $expectedRepositoryNames) {
  if (-not $repositoriesByName.ContainsKey($repositoryName)) {
    Add-Failure -Failures $failures -Message "ECR repository '$repositoryName' was not found in Terraform state."
    continue
  }

  $repositoryUrl = $repositoriesByName[$repositoryName]
  $repositoryResponse = Invoke-AwsJson -Arguments @("ecr", "describe-repositories", "--repository-names", $repositoryName, "--region", $region)
  $describedRepository = @($repositoryResponse.repositories)[0]

  if ($describedRepository.repositoryUri -eq $repositoryUrl) {
    Add-Success "ECR repository '$repositoryName' exists."
  } else {
    Add-Failure -Failures $failures -Message "ECR repository '$repositoryName' did not match the Terraform output URI."
  }
}

if ($failures.Count -gt 0) {
  Write-Host ""
  Write-Host "Verification failed:" -ForegroundColor Red

  foreach ($failure in $failures) {
    Write-Host " - $failure" -ForegroundColor Red
  }

  exit 1
}

Write-Host ""
Write-Host "Terraform-managed AWS resources verified successfully." -ForegroundColor Green