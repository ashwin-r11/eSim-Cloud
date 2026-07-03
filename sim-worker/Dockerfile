# Stage 1: Build ngspice from source on Alpine
FROM alpine:3.18 AS ngspice-builder

RUN apk add --no-cache \
    autoconf \
    automake \
    bison \
    flex \
    g++ \
    libtool \
    make \
    curl \
    tar

ENV NGSPICE_VERSION=40
RUN curl -fSL https://github.com/imr/ngspice/archive/ngspice-${NGSPICE_VERSION}.tar.gz \
        -o ngspice.tar.gz \
    && tar -xzf ngspice.tar.gz -C /usr/src/ \
    && cd /usr/src/ngspice-ngspice-${NGSPICE_VERSION} \
    && ./autogen.sh \
    && ./configure \
        --with-x=no \
        --with-readline=no \
        --disable-xspice \
        --disable-cider \
        --disable-gpu \
        --disable-openmp \
    && make -j"$(nproc)" \
    && make install

# Stage 2: Runtime image
FROM python:3.12-alpine

# Install libstdc++ required by the ngspice binary
RUN apk add --no-cache libstdc++

# Copy only the built ngspice binary + share files
COPY --from=ngspice-builder /usr/local/bin/ngspice /usr/local/bin/ngspice
COPY --from=ngspice-builder /usr/local/share/ngspice /usr/local/share/ngspice

WORKDIR /srv/sim-worker

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Create a non-root user and scratch directory (Task 5 – least privilege)
RUN adduser -D -u 1001 simworker \
    && mkdir -p /tmp/esim_simulations \
    && chown simworker:simworker /tmp/esim_simulations

USER simworker

ENV HOST=0.0.0.0 \
    PORT=8001 \
    LOG_LEVEL=INFO \
    SIM_SCRATCH_DIR=/tmp/esim_simulations

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget -qO- http://localhost:${PORT}/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
