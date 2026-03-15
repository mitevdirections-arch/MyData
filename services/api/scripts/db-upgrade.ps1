#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot/..
py -m alembic -c alembic.ini upgrade head
