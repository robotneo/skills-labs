import json
import argparse
from client import VCenterClient
from inventory import VCenterInventory
from executor import VCenterExecutor

def handle_request():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--pwd", required=True)
    # 动作参数
    parser.add_argument("--vm_name", help="VM Name")
    parser.add_argument("--template", help="Template Name")
    parser.add_argument("--dc", help="Datacenter Name")
    parser.add_argument("--cluster", help="Cluster Name")
    parser.add_argument("--ds", help="Datastore Name")
    
    args = parser.parse_args()

    try:
        with VCenterClient(args.host, args.user, args.pwd) as si:
            inv = VCenterInventory(si)
            exe = VCenterExecutor(si)

            if args.action == "list_all":
                result = inv.get_all_resources()
            elif args.action == "get_vm":
                result = inv.find_vm_detail(args.vm_name)
            elif args.action == "clone":
                result = exe.clone_vm(args.template, args.vm_name, args.dc, args.cluster, args.ds)
            elif args.action == "delete":
                result = exe.delete_vm(args.vm_name)
            else:
                result = {"error": "未知的动作指令"}

            print(json.dumps({"status": "success", "data": result}, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))

if __name__ == "__main__":
    handle_request()