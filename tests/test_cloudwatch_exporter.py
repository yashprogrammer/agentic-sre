from sre_agent.detection.cloudwatch_exporter import metric_data


def test_metrics_report_actual_latency_only_for_correct_requests():
    sample={'finished_at':1700000000,'valid':1,'elapsed_ms':4007}
    values={x['MetricName']:x['Value'] for x in metric_data(sample)}
    assert values=={'CatalogSearchCorrect':1.0,'CatalogSearchLatencyMs':4007.0}
    assert all(x['StorageResolution']==1 for x in metric_data(sample))
    values={x['MetricName']:x['Value'] for x in metric_data(sample | {'valid':0})}
    assert values=={'CatalogSearchCorrect':0.0}
