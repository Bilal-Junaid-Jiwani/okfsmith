---
type: Metric
title: Income statement (fiscal year)
description: Headline income-statement figures for a fiscal year.
tags: [finance, income-statement]
timestamp: '2026-05-28T22:53:05+00:00'
---

# Definition

The income statement reports revenue and gross profit for a fiscal year.

# Revenue

Recognized revenue sums `amount` over rows booked to the fiscal year:

  SELECT SUM(amount) AS revenue
  FROM finance.recognized_revenue
  WHERE fiscal_year = @year

# Gross profit

Gross profit by segment, per the cost-allocation standard:

  SELECT gross_profit FROM fct_income_statement
  WHERE fiscal_year = @year AND segment = @segment

# Citations

- https://wiki.acme/finance/fpa-handbook
- https://wiki.acme/finance/revenue-recognition
- https://wiki.acme/finance/cost-allocation
