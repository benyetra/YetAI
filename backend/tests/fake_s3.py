"""In-memory S3 client for model_store tests (get/head/put/copy/list)."""

from __future__ import annotations

import io


class ClientError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = dict(objects or {})
        self.etags: dict[str, str] = {k: "e1" for k in self.objects}
        self.calls: list[tuple] = []
        self.fail_head = False

    def put(self, key: str, body: bytes, etag: str) -> None:
        self.objects[key] = body
        self.etags[key] = etag

    def head_object(self, Bucket, Key):
        self.calls.append(("head", Key))
        if self.fail_head:
            raise ClientError("500")
        if Key not in self.objects:
            raise ClientError("404")
        return {"ETag": self.etags[Key]}

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Key))
        if Key not in self.objects:
            raise ClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body):
        self.calls.append(("put", Key))
        self.put(Key, Body, f"e{len(self.calls)}")

    def copy_object(self, Bucket, Key, CopySource):
        src = CopySource["Key"]
        self.calls.append(("copy", src, Key))
        if src not in self.objects:
            raise ClientError("NoSuchKey")
        self.put(Key, self.objects[src], self.etags[src])

    def list_objects_v2(self, Bucket, Prefix, Delimiter, **_):
        prefixes = {
            Prefix + k[len(Prefix) :].split("/", 1)[0] + "/"
            for k in self.objects
            if k.startswith(Prefix) and "/" in k[len(Prefix) :]
        }
        return {"CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)]}

    def names(self, op: str) -> list:
        return [c for c in self.calls if c[0] == op]


class Static:
    """Stands in for an S3Object that already holds ``value``."""

    def __init__(self, value, version=None):
        self.value, self.version = value, version

    def get(self):
        return self.value
