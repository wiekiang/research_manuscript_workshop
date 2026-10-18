# Sandboxed experiment image: pinned Python base (digest), pinned scientific packages, unprivileged user.
# Runs only with --network none, read-only root, tmpfs workspace and resource limits (rp_latex.sandbox.DockerSandbox).
FROM python@sha256:9d72651cf7018c1f6a1dd6fd02bd68286631c33620bc0f37b0675b21aab915d5
COPY requirements.txt envinfo.py /opt/rp/
RUN pip install --no-cache-dir -r /opt/rp/requirements.txt \
 && python /opt/rp/envinfo.py \
 && useradd -u 10001 -M -s /usr/sbin/nologin runner
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 HOME=/tmp MPLCONFIGDIR=/tmp
USER 10001:10001
WORKDIR /work
