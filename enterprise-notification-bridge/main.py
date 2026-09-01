from __future__ import absolute_import

import sys

from notification_bridge.cli import main as cli_main
from notification_bridge.mcp_server import main as mcp_main


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["mcp"]:
        return mcp_main()
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
