# Sandboxed LaTeX image: fixed TeX Live, whitelisted packages, unprivileged user, shell escape disabled.
# Base pinned by digest (see infra/images.lock). Installed package revisions are exported to tlpkg.lock.
FROM texlive/texlive@sha256:956ab3808fc77b0057c0f8b6db5329642b8db7a33492460b9891862b72334f3c
ARG TL_REPO=https://mirrors.ibiblio.org/pub/mirrors/CTAN/systems/texlive/tlnet
COPY packages.txt /tmp/packages.txt
RUN tlmgr option repository "$TL_REPO" && (tlmgr update --self || (sleep 10 && tlmgr update --self))
RUN grep -v '^#' /tmp/packages.txt | tr ' ' '\n' | grep -v '^$' > /tmp/pkgs \
 && (xargs tlmgr install < /tmp/pkgs || (sleep 10 && xargs tlmgr install < /tmp/pkgs)) \
 && (tlmgr update --all || (sleep 10 && tlmgr update --all))
RUN tlmgr conf texmf shell_escape f \
 && tlmgr conf texmf openout_any p \
 && tlmgr conf texmf openin_any p \
 && mkdir -p /usr/local/share/rp && tlmgr info --only-installed --data name,localrev > /usr/local/share/rp/tlpkg.lock \
 && useradd -u 10001 -M -s /usr/sbin/nologin tex \
 && rm -rf /tmp/packages.txt /tmp/pkgs /usr/local/texlive/*/tlpkg/backups/*
USER 10001:10001
ENV TEXMFVAR=/tmp/texmf-var HOME=/tmp
WORKDIR /work
