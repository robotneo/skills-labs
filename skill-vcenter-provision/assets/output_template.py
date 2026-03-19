def format_output(data):
    return f"""
【虚拟机开通信息】

系统：{data['os']}
规格：{data['cpu']}C / {data['memory']}G / {data['disk']}G
主机名：{data['hostname']}
IP地址：{data['ip']}
宿主机：{data['host']}
"""