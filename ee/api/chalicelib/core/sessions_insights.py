import schemas, schemas_ee
from typing import List
from chalicelib.core import metrics
from chalicelib.utils import ch_client


def _table_slice(table, index):
    col = list()
    for row in table:
        col.append(row[index])
    return col


def _table_where(table, index, value):
    new_table = list()
    for row in table:
        if row[index] == value:
            new_table.append(row)
    return new_table


def _sum_table_index(table, index):
    s = 0
    count = 0
    for row in table:
        v = row[index]
        if v is None:
            continue
        s += v
        count += 1
    return s


def _mean_table_index(table, index):
    s = _sum_table_index(table, index)
    c = len(table)
    return s / c


def _sort_table_index(table, index, reverse=False):
    return sorted(table, key=lambda k: k[index], reverse=reverse)


def _select_rec(l, selector):
    print('selector:', selector)
    print('list:', l)
    if len(selector) == 1:
        return l[selector[0]]
    else:
        s = selector[0]
        L = l[s]
        type_ = type(s)
        if type_ == slice:
            return [_select_rec(l_, selector[1:]) for l_ in L]
        elif type_ == int:
            return [_select_rec(L, selector[1:])]


# TODO Deal with None values

def __get_two_values(response, time_index='hh', name_index='name'):
    columns = list(response[0].keys())
    name_index_val = columns.index(name_index)
    time_index_value = columns.index(time_index)

    table = [list(r.values()) for r in response]
    table_hh1 = list()
    table_hh2 = list()
    hh_vals = list()
    names_hh1 = list()
    names_hh2 = list()
    for e in table:
        if e[time_index_value] not in hh_vals and len(hh_vals) == 2:
            break
        elif e[time_index_value] not in hh_vals:
            hh_vals.append(e[time_index_value])

        if len(hh_vals) == 1:
            table_hh1.append(e)
            if e[name_index_val] not in names_hh1:
                names_hh1.append(e[name_index_val])
        elif len(hh_vals) == 2:
            table_hh2.append(e)
            if e[name_index_val] not in names_hh2:
                names_hh2.append(e[name_index_val])
    return table_hh1, table_hh2, columns, names_hh1, names_hh2


def __handle_timestep(time_step):
    base = "{0}"
    if time_step == 'hour':
        return f"toStartOfHour({base})", 3600
    elif time_step == 'day':
        return f"toStartOfDay({base})", 24 * 3600
    elif time_step == 'week':
        return f"toStartOfWeek({base})", 7 * 24 * 3600
    else:
        assert type(
            time_step) == int, "time_step must be {'hour', 'day', 'week'} or an integer representing the time step in minutes"
        return f"toStartOfInterval({base}, INTERVAL {time_step} minute)", int(time_step) * 60


def query_requests_by_period(project_id, start_time, end_time):
    params = {
        "project_id": project_id, "startTimestamp": start_time, "endTimestamp": end_time,
        "step_size": metrics.__get_step_size(endTimestamp=end_time, startTimestamp=start_time, density=3)
    }
    conditions = ["event_type = 'REQUEST'"]
    query = f"""WITH toUInt32(toStartOfInterval(toDateTime(%(startTimestamp)s/1000), INTERVAL %(step_size)s second)) AS start,
                     toUInt32(toStartOfInterval(toDateTime(%(endTimestamp)s/1000), INTERVAL %(step_size)s second)) AS end
                SELECT T1.hh, count(T2.session_id) as sessions, avg(T2.success) as success_rate, T2.url_host as names, 
                        T2.url_path as source, avg(T2.duration) as avg_duration 
                FROM (SELECT arrayJoin(arrayMap(x -> toDateTime(x), range(start, end, %(step_size)s))) as hh) AS T1
                LEFT JOIN (SELECT session_id, url_host, url_path, success, message, duration, toStartOfInterval(datetime, INTERVAL %(step_size)s second) as dtime 
                           FROM experimental.events 
                           WHERE project_id = {project_id} 
                                AND {" AND ".join(conditions)}) AS T2 ON T2.dtime = T1.hh 
                GROUP BY T1.hh, T2.url_host, T2.url_path 
                ORDER BY T1.hh DESC;"""
    with ch_client.ClickHouseClient() as conn:
        query = conn.format(query=query, params=params)
        res = conn.execute(query=query)

    table_hh1, table_hh2, columns, this_period_hosts, last_period_hosts = __get_two_values(res, time_index='hh',
                                                                                           name_index='source')
    test = [k[4] for k in table_hh1]
    print(f'length {len(test)}, uniques {len(set(test))}')
    del res

    new_hosts = [x for x in this_period_hosts if x not in last_period_hosts]
    common_names = [x for x in this_period_hosts if x not in new_hosts]

    source_idx = columns.index('source')
    duration_idx = columns.index('avg_duration')
    # success_idx = columns.index('success_rate')
    # delta_duration = dict()
    # delta_success = dict()
    new_duration_values = dict()
    duration_values = dict()
    for n in common_names:
        d1_tmp = _table_where(table_hh1, source_idx, n)
        d2_tmp = _table_where(table_hh2, source_idx, n)
        old_duration = _mean_table_index(d2_tmp, duration_idx)
        new_duration = _mean_table_index(d1_tmp, duration_idx)
        if old_duration == 0:
            continue
        duration_values[n] = new_duration, old_duration, (new_duration - old_duration) / old_duration
        # delta_duration[n] = (_mean_table_index(d1_tmp, duration_idx) - _duration1) / _duration1
        # delta_success[n] = _mean_table_index(d1_tmp, success_idx) - _mean_table_index(d2_tmp, success_idx)
    for n in new_hosts:
        d1_tmp = _table_where(table_hh1, source_idx, n)
        new_duration_values[n] = _mean_table_index(d1_tmp, duration_idx)

        # names_idx = columns.index('names')
    total = _sum_table_index(table_hh1, duration_idx)
    d1_tmp = _sort_table_index(table_hh1, duration_idx, reverse=True)
    _tmp = _table_slice(d1_tmp, duration_idx)
    _tmp2 = _table_slice(d1_tmp, source_idx)

    increase = sorted(duration_values.items(), key=lambda k: k[1][-1], reverse=True)
    ratio = sorted(zip(_tmp2, _tmp), key=lambda k: k[1], reverse=True)
    # names_ = set([k[0] for k in increase[:3]+ratio[:3]]+new_hosts[:3])
    names_ = set([k[0] for k in increase[:3] + ratio[:3]])  # we took out new hosts since they dont give much info

    results = list()
    for n in names_:
        if n is None:
            continue
        data_ = {'category': 'network', 'name': n, 'value': None, 'oldValue': None, 'ratio': None, 'change': None,
                 'isNew': True}
        for n_, v in ratio:
            if n == n_:
                if n in new_hosts:
                    data_['value'] = new_duration_values[n]
                data_['ratio'] = v / total
                break
        for n_, v in increase:
            if n == n_:
                data_['value'] = v[0]
                data_['oldValue'] = v[1]
                data_['change'] = v[2]
                data_['isNew'] = False
                break
        results.append(data_)
    return results


def query_most_errors_by_period(project_id, start_time, end_time):
    params = {
        "project_id": project_id, "startTimestamp": start_time, "endTimestamp": end_time,
        "step_size": metrics.__get_step_size(endTimestamp=end_time, startTimestamp=start_time, density=3)
    }
    conditions = ["event_type = 'ERROR'"]
    query = f"""WITH toUInt32(toStartOfInterval(toDateTime(%(startTimestamp)s/1000), INTERVAL %(step_size)s second)) AS start,
                     toUInt32(toStartOfInterval(toDateTime(%(endTimestamp)s/1000), INTERVAL %(step_size)s second)) AS end
                SELECT T1.hh, count(T2.session_id) as sessions, T2.name as names, 
                        groupUniqArray(T2.source) as sources 
                FROM (SELECT arrayJoin(arrayMap(x -> toDateTime(x), range(start, end, %(step_size)s))) as hh) AS T1
                    LEFT JOIN (SELECT session_id, name, source, message, toStartOfInterval(datetime, INTERVAL %(step_size)s second) as dtime
                               FROM experimental.events 
                               WHERE project_id = {project_id}
                                    AND datetime >= toDateTime(%(startTimestamp)s/1000)
                                    AND datetime < toDateTime(%(endTimestamp)s/1000)
                                    AND {" AND ".join(conditions)}) AS T2 ON T2.dtime = T1.hh 
                GROUP BY T1.hh, T2.name 
                ORDER BY T1.hh DESC;"""

    with ch_client.ClickHouseClient() as conn:
        query = conn.format(query=query, params=params)
        res = conn.execute(query=query)

    table_hh1, table_hh2, columns, this_period_errors, last_period_errors = __get_two_values(res, time_index='hh',
                                                                                             name_index='names')
    del res

    new_errors = [x for x in this_period_errors if x not in last_period_errors]
    common_errors = [x for x in this_period_errors if x not in new_errors]

    sessions_idx = columns.index('sessions')
    names_idx = columns.index('names')
    percentage_errors = dict()
    total = _sum_table_index(table_hh1, sessions_idx)
    # error_increase = dict()
    new_error_values = dict()
    error_values = dict()
    for n in this_period_errors:
        percentage_errors[n] = _sum_table_index(_table_where(table_hh1, names_idx, n), sessions_idx)
        new_error_values[n] = _sum_table_index(_table_where(table_hh1, names_idx, n), names_idx)
    for n in common_errors:
        old_errors = _sum_table_index(_table_where(table_hh2, names_idx, n), names_idx)
        if old_errors == 0:
            continue
        new_errors = _sum_table_index(_table_where(table_hh1, names_idx, n), names_idx)
        # error_increase[n] = (new_errors - old_errors) / old_errors
        error_values[n] = new_errors, old_errors, (new_errors - old_errors) / old_errors
    ratio = sorted(percentage_errors.items(), key=lambda k: k[1], reverse=True)
    increase = sorted(error_values.items(), key=lambda k: k[1][-1], reverse=True)
    names_ = set([k[0] for k in increase[:3] + ratio[:3]] + new_errors[:3])

    results = list()
    for n in names_:
        if n is None:
            continue
        data_ = {'category': 'errors', 'name': n, 'value': None, 'oldValue': None, 'ratio': None, 'change': None,
                 'isNew': True}
        for n_, v in ratio:
            if n == n_:
                if n in new_errors:
                    data_['value'] = new_error_values[n]
                data_['ratio'] = v / total
                break
        for n_, v in increase:
            if n == n_:
                data_['value'] = v[0]
                data_['oldValue'] = v[1]
                data_['change'] = v[2]
                data_['isNew'] = False
                break
        results.append(data_)
    return results


def query_cpu_memory_by_period(project_id, start_time, end_time):
    params = {
        "project_id": project_id, "startTimestamp": start_time, "endTimestamp": end_time,
        "step_size": metrics.__get_step_size(endTimestamp=end_time, startTimestamp=start_time, density=3)
    }
    conditions = ["event_type = 'PERFORMANCE'"]
    query = f"""WITH toUInt32(toStartOfInterval(toDateTime(%(startTimestamp)s/1000), INTERVAL %(step_size)s second)) AS start,
                     toUInt32(toStartOfInterval(toDateTime(%(endTimestamp)s/1000), INTERVAL %(step_size)s second)) AS end
                SELECT T1.hh, count(T2.session_id) as sessions, avg(T2.avg_cpu) as cpu_used, 
                        avg(T2.avg_used_js_heap_size) as memory_used, T2.url_host as names, groupUniqArray(T2.url_path) as sources 
                FROM (SELECT arrayJoin(arrayMap(x -> toDateTime(x), range(start, end, %(step_size)s))) as hh) AS T1
                LEFT JOIN (SELECT session_id, url_host, url_path, avg_used_js_heap_size, avg_cpu, toStartOfInterval(datetime, INTERVAL %(step_size)s second) as dtime 
                           FROM experimental.events 
                           WHERE project_id = {project_id} 
                                AND {" AND ".join(conditions)}) AS T2 ON T2.dtime = T1.hh 
                GROUP BY T1.hh, T2.url_host 
                ORDER BY T1.hh DESC;"""
    with ch_client.ClickHouseClient() as conn:
        query = conn.format(query=query, params=params)
        res = conn.execute(query=query)

    table_hh1, table_hh2, columns, this_period_resources, last_period_resources = __get_two_values(res, time_index='hh',
                                                                                                   name_index='names')
    del res

    memory_idx = columns.index('memory_used')
    cpu_idx = columns.index('cpu_used')

    mem_newvalue = _mean_table_index(table_hh1, memory_idx)
    mem_oldvalue = _mean_table_index(table_hh2, memory_idx)
    cpu_newvalue = _mean_table_index(table_hh2, cpu_idx)
    cpu_oldvalue = _mean_table_index(table_hh2, cpu_idx)
    # TODO: what if _tmp=0 ?
    mem_oldvalue = 1 if mem_oldvalue == 0 else mem_oldvalue
    cpu_oldvalue = 1 if cpu_oldvalue == 0 else cpu_oldvalue
    return [{'category': 'resources',
             'name': 'cpu',
             'value': cpu_newvalue,
             'oldValue': cpu_oldvalue,
             'change': (cpu_newvalue - cpu_oldvalue) / cpu_oldvalue,
             'isNew': None},
            {'category': 'resources',
             'name': 'memory',
             'value': mem_newvalue,
             'oldValue': mem_oldvalue,
             'change': (mem_newvalue - mem_oldvalue) / mem_oldvalue,
             'isNew': None}
            ]


def query_click_rage_by_period(project_id, start_time, end_time):
    params = {
        "project_id": project_id, "startTimestamp": start_time, "endTimestamp": end_time,
        "step_size": metrics.__get_step_size(endTimestamp=end_time, startTimestamp=start_time, density=3)}

    conditions = ["issue_type = 'click_rage'", "event_type = 'ISSUE'"]
    query = f"""WITH toUInt32(toStartOfInterval(toDateTime(%(startTimestamp)s/1000), INTERVAL %(step_size)s second)) AS start,
                     toUInt32(toStartOfInterval(toDateTime(%(endTimestamp)s/1000), INTERVAL %(step_size)s second)) AS end
                SELECT T1.hh, count(T2.session_id) as sessions, groupUniqArray(T2.url_host) as names, T2.url_path as sources 
                FROM (SELECT arrayJoin(arrayMap(x -> toDateTime(x), range(start, end, %(step_size)s))) as hh) AS T1
                LEFT JOIN (SELECT session_id, url_host, url_path, toStartOfInterval(datetime, INTERVAL %(step_size)s second ) as dtime 
                           FROM experimental.events 
                           WHERE project_id = %(project_id)s 
                                AND datetime >= toDateTime(%(startTimestamp)s/1000)
                                AND datetime < toDateTime(%(endTimestamp)s/1000)
                                AND {" AND ".join(conditions)}) AS T2 ON T2.dtime = T1.hh 
                GROUP BY T1.hh, T2.url_path 
                ORDER BY T1.hh DESC;"""
    with ch_client.ClickHouseClient() as conn:
        query = conn.format(query=query, params=params)
        res = conn.execute(query=query)

    table_hh1, table_hh2, columns, this_period_rage, last_period_rage = __get_two_values(res, time_index='hh',
                                                                                         name_index='sources')
    del res

    new_names = [x for x in this_period_rage if x not in last_period_rage]
    common_names = [x for x in this_period_rage if x not in new_names]

    sessions_idx = columns.index('sessions')
    names_idx = columns.index('sources')

    # raged_increment = dict()
    raged_values = dict()
    new_raged_values = dict()
    # TODO verify line (188) _tmp = table_hh2[:, sessions_idx][n].sum()
    for n in common_names:
        if n is None:
            continue
        _oldvalue = _sum_table_index(_table_where(table_hh2, names_idx, n), sessions_idx)
        _newvalue = _sum_table_index(_table_where(table_hh1, names_idx, n), sessions_idx)
        # raged_increment[n] = (_newvalue - _oldvalue) / _oldvalue
        raged_values[n] = _newvalue, _oldvalue, (_newvalue - _oldvalue) / _oldvalue

    for n in new_names:
        if n is None:
            continue
        _newvalue = _sum_table_index(_table_where(table_hh1, names_idx, n), sessions_idx)
        new_raged_values[n] = _newvalue

    total = _sum_table_index(table_hh1, sessions_idx)
    names, ratio = _table_slice(table_hh1, names_idx), _table_slice(table_hh1, sessions_idx)
    ratio = sorted(zip(names, ratio), key=lambda k: k[1], reverse=True)
    increase = sorted(raged_values.items(), key=lambda k: k[1][-1], reverse=True)
    names_ = set([k[0] for k in increase[:3] + ratio[:3]] + new_names[:3])

    results = list()
    for n in names_:
        if n is None:
            continue
        data_ = {'category': 'rage', 'name': n, 'value': None, 'oldValue': None, 'ratio': None, 'change': None,
                 'isNew': True}
        for n_, v in ratio:
            if n == n_:
                if n in new_names:
                    data_['value'] = new_raged_values[n]
                data_['ratio'] = v / total
                break
        for n_, v in increase:
            if n == n_:
                data_['value'] = v[0]
                data_['oldValue'] = v[1]
                data_['change'] = v[2]
                data_['isNew'] = False
                break
        results.append(data_)
    return results


def fetch_selected(project_id, data: schemas_ee.GetInsightsSchema):
    output = list()
    # TODO: Handle filters of GetInsightsSchema
    # data.series[0].filter.filters
    if data.metricValue is None or len(data.metricValue) == 0:
        data.metricValue = []
        for v in schemas_ee.InsightCategories:
            data.metricValue.append(v)
    if schemas_ee.InsightCategories.errors in data.metricValue:
        output += query_most_errors_by_period(project_id=project_id,
                                              start_time=data.startTimestamp,
                                              end_time=data.endTimestamp)
    if schemas_ee.InsightCategories.network in data.metricValue:
        output += query_requests_by_period(project_id=project_id,
                                           start_time=data.startTimestamp,
                                           end_time=data.endTimestamp)
    if schemas_ee.InsightCategories.rage in data.metricValue:
        output += query_click_rage_by_period(project_id=project_id,
                                             start_time=data.startTimestamp,
                                             end_time=data.endTimestamp)
        if schemas_ee.InsightCategories.resources in data.metricValue:
            output += query_cpu_memory_by_period(project_id=project_id,
                                                 start_time=data.startTimestamp,
                                                 end_time=data.endTimestamp)
    return output
