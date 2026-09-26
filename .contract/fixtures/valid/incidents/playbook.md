---
type: Playbook
title: "Incident response: data freshness alert"
description: Steps to triage a freshness alert on the orders pipeline.
tags: [oncall, incident]
generated: { by: human:ahormati, at: 2026-04-12T09:00:00Z }
---

# Trigger

A freshness alert fires when `orders` lags more than 30 minutes behind its expected SLA. See the [orders table](/finance/revenue).

# Steps

1. Check the ingestion dashboard.
2. Page the oncall.
