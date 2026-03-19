import json
from core.planner import plan_provision
from assets.output_template import format_output

def execute(args, context=None):
    try:
        plan = plan_provision(args)

        # 二次确认
        if not context or not context.get("confirmed"):
            return {
                "type": "confirm",
                "message": "请确认虚拟机创建计划",
                "data": plan
            }

        # 模拟执行
        result = {
            "status": "success",
            **plan
        }

        return {
            "type": "result",
            "message": format_output(result),
            "data": result
        }

    except Exception as e:
        return {
            "type": "error",
            "message": str(e)
        }


if __name__ == "__main__":
    args = {"hostname": "test001"}
    res = execute(args, context={"confirmed": True})
    print(json.dumps(res, indent=2, ensure_ascii=False))