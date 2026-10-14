"""OVA/OVF validation core (no SDK import).

The hard, testable safety boundary is local archive extraction: an OVA entry
must never escape the target directory. Descriptor and network/disk mapping
validation are pure logic so they can be fully exercised offline.
"""
import io
import os
import posixpath
import re
import tarfile

from ...domain.models import fail


UNSAFE_ENTRY = re.compile(r"^[\\/]|[A-Za-z]:")


def safe_member_name(name):
    """Return a normalized relative entry path or None when unsafe."""
    if not name or "\x00" in name:
        return None
    normalized = name.replace("\\", "/")
    if UNSAFE_ENTRY.match(normalized):
        return None
    parts = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return None
    candidate = posixpath.join(*parts)
    if candidate.startswith("/") or os.path.isabs(candidate):
        return None
    return candidate


def safe_members(tar):
    """Yield safe members; raise on any path traversal / link escape."""
    for member in tar.getmembers():
        target = safe_member_name(member.name)
        if target is None:
            fail("ovf_unsafe_path", f"OVA 条目路径不安全：{member.name!r}；拒绝解包", 2)
        if member.issym() or member.islnk():
            link = safe_member_name(member.linkname)
            if link is None:
                fail("ovf_unsafe_link", f"OVA 条目链接逃逸：{member.name!r}；拒绝解包", 2)
            # A link may only point inside the extraction tree; the normalized
            # link is checked to stay under the base at extraction time too.
        member.name = target
        yield member


def extract_ova(archive, destination):
    """Extract a local OVA tar safely into destination."""
    if os.path.islink(destination):
        fail("ovf_destination_invalid", "目标目录不能是符号链接", 2)
    os.makedirs(destination, exist_ok=True)
    base = os.path.realpath(destination)
    with tarfile.open(archive, mode="r:*") as tar:
        for member in safe_members(tar):
            output = os.path.realpath(os.path.join(base, member.name))
            if output != base and not output.startswith(base + os.sep):
                fail("ovf_unsafe_path", "解包后路径越界，拒绝解包", 2)
            if member.isdir():
                os.makedirs(output, exist_ok=True)
                continue
            parent = os.path.dirname(output)
            os.makedirs(parent, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    os.write(descriptor, chunk)
            finally:
                os.close(descriptor)
    return base


def _strip_namespace(xml):
    return re.sub(r"\sxmlns(?::\w+)?=\"[^\"]*\"", "", xml)


def parse_descriptor(xml_text):
    """Extract networks and file references from an OVF descriptor."""
    body = _strip_namespace(xml_text or "")
    networks = re.findall(
        r"<Network[^>]*\bname=\"([^\"]+)\"", body)
    if not networks:
        networks = re.findall(r"<Network\b[^>]*>", body)
        networks = [re.search(r"\bovf:name=\"([^\"]+)\"", n).group(1)
                    if re.search(r"\bovf:name=\"([^\"]+)\"", n) else None
                    for n in networks]
        networks = [n for n in networks if n]
    references = re.findall(
        r"<File\b[^>]*\bovf:href=\"([^\"]+)\"[^>]*/?>", body)
    if not references:
        references = re.findall(r"<File\b[^>]*\bhref=\"([^\"]+)\"", body)
    return {"networks": networks, "files": references}


def validate_mapping(descriptor, network_mapping, present_files):
    """Check every descriptor network is mapped and referenced files exist."""
    descriptor = parse_descriptor(descriptor)
    networks = descriptor["networks"]
    if network_mapping is None:
        network_mapping = {}
    missing_networks = [n for n in networks if n not in network_mapping]
    if missing_networks:
        fail("ovf_network_mapping_incomplete",
             f"描述符网络未完整映射：{missing_networks}", 2)
    present = set(present_files or [])
    missing_files = [f for f in descriptor["files"] if f not in present]
    if missing_files:
        fail("ovf_file_missing",
             f"描述符引用磁盘缺失：{missing_files}", 2)
    invalid_targets = [v for v in network_mapping.values()
                       if not re.fullmatch(r"(?:dvportgroup|network)-\d+", str(v))]
    if invalid_targets:
        fail("ovf_network_target_invalid",
             "网络映射目标须为精确 network-N/dvportgroup-N 对象 ID", 2)
    return {"networks": networks, "files": descriptor["files"],
            "network_mapping": dict(network_mapping)}


def validate_placement(params):
    """Validate required placement identifiers for an OVA/OVF deploy."""
    required = ("resource_pool_id", "host_id", "folder_id", "datastore_id")
    missing = [key for key in required if not params.get(key)]
    if missing:
        fail("invalid_arguments", f"部署缺少放置参数：{missing}", 2)
    patterns = {"resource_pool_id": r"resgroup-\d+", "host_id": r"host-\d+",
                "folder_id": r"group-[vfs]\d+", "datastore_id": r"datastore-\d+"}
    for key, pattern in patterns.items():
        if not re.fullmatch(pattern, params[key]):
            fail("target_invalid", f"放置参数 {key} 不是精确对象 ID", 2)
    return True
