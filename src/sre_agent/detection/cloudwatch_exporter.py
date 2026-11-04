"""Publish a bounded stream of real demo-probe observations to CloudWatch.

SQLite is the source of truth. This best-effort exporter deliberately never
retries an uncertain metric write; missing metrics remain missing.
"""
import datetime
import time
from contextlib import closing

from sre_agent.catalog.app import connect

NAMESPACE = 'AgenticSRE/DemoShop'


def metric_data(sample):
    timestamp = datetime.datetime.fromtimestamp(sample['finished_at'], datetime.timezone.utc)
    data = [{'MetricName':'CatalogSearchCorrect', 'Timestamp':timestamp, 'Value':float(bool(sample['valid'])), 'Unit':'Count', 'StorageResolution':1}]
    if sample['valid']:
        data.append({'MetricName':'CatalogSearchLatencyMs','Timestamp':timestamp,'Value':float(sample['elapsed_ms']),'Unit':'Milliseconds','StorageResolution':1})
    return data


def main():
    import boto3
    from botocore.config import Config
    client = boto3.client('cloudwatch', region_name='us-east-1', config=Config(connect_timeout=3, read_timeout=4, retries={'total_max_attempts':1}))
    last_id = None
    print('CloudWatch exporter started.', flush=True)
    while True:
        try:
            with closing(connect()) as db:
                sample = db.execute('SELECT * FROM probe_samples ORDER BY started_at DESC LIMIT 1').fetchone()
            if sample and sample['id'] != last_id:
                last_id = sample['id']
                if 0 <= time.time() - sample['finished_at'] <= 20:
                    client.put_metric_data(Namespace=NAMESPACE, MetricData=metric_data(sample))
        except Exception as exc:
            print('CloudWatch export unavailable:', type(exc).__name__, flush=True)
        time.sleep(5)


if __name__ == '__main__':main()
