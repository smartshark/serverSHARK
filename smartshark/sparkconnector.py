import server.settings
import requests
import json
import re

class BatchJob(object):
    def __init__(self, id, state, log):
        self.id = id
        self.state = state
        self.log = log


    def __str__(self):
        return 'id: %s, state: %s, log: %s' % (self.id, self.state, '\n'.join(self.log))


class SparkConnector(object):

    def __init__(self):
        self.address = "http://%s:%s" % (server.settings.SPARK_MASTER['host'], server.settings.SPARK_MASTER['port'])
        self.json_header = {'Content-Type': 'application/json'}

        self.batches_endpoint = self.address + '/batches'

    def submit_batch_job(self, file_path, proxy_user=None, class_name=None, args=[], conf=None):
        # Create data stuff
        data = {
            'file': file_path,
            'proxy_user': proxy_user,
            'class_name': class_name,
            'args': args,
            'conf': conf
        }

        # filter out if empty or none
        data = {k: v for k, v in data.items() if v is not None and v}
        ret = requests.post(self.batches_endpoint, data=json.dumps(data), headers=self.json_header)
        return self.create_batch_object(ret.json())

    def get_active_batch_jobs(self):
        ret = requests.get(self.batches_endpoint)
        batch_jobs = []
        for batch_job in ret.json()['sessions']:
            batch_jobs.append(self.create_batch_object(batch_job))

        return batch_jobs

    def get_log_from_batch_job(self, batch_id, from_log=0, size_log=2000, only_user_output=False):
        payload = {'from': from_log, 'size': size_log}
        ret = requests.get(self.batches_endpoint+'/'+str(batch_id)+'/log', params=payload)

        if only_user_output:
            pattern = re.compile("\d{2}[:/]\d{2}[:/]\d{2}")
            output = []
            for line in ret.json()['log'][1:]:
                if pattern.match(line) is None:
                    output.append(line)
            return '\n'.join(output)
        else:
            return '\n'.join(ret.json()['log'])

    def kill_batch_job(self, batch_id):
        ret = requests.delete(self.batches_endpoint+'/'+str(batch_id))

        if ret.json()['msg'] == 'deleted':
            return True

        return False


    @staticmethod
    def create_batch_object(data_dict):
        return BatchJob(data_dict['id'], data_dict['state'], data_dict['log'])


#sc = SparkConnector()
#bj = sc.submit_batch_job('/home/ftrauts/Arbeit/spark/examples/src/main/python/pi.py')
#print(sc.get_log_from_batch_job(4, only_user_output=True))