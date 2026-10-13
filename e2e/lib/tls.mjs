// Throwaway TLS material for one end-to-end run: a local CA and a localhost
// server certificate signed by it. Every process in the run trusts only this
// CA (API: SSL_CERT_FILE; Node: NODE_EXTRA_CA_CERTS), so certificate and host
// name verification stay fully on: nothing disables TLS checks.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

const CA_EXTENSIONS = `
[req]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no
[dn]
CN = HeroOS E2E throwaway CA
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
`;

const LEAF_EXTENSIONS = `
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:localhost, IP:127.0.0.1
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
`;

function openssl(args, cwd) {
  execFileSync("openssl", args, { cwd, stdio: ["ignore", "ignore", "pipe"] });
}

/** Creates ca.pem, server.pem and server-key.pem in `dir`; returns their paths. */
export function createTlsMaterial(dir) {
  writeFileSync(join(dir, "ca.cnf"), CA_EXTENSIONS);
  writeFileSync(join(dir, "leaf.ext"), LEAF_EXTENSIONS);
  openssl(["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-config", "ca.cnf",
    "-keyout", "ca-key.pem", "-out", "ca.pem"], dir);
  openssl(["req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost",
    "-keyout", "server-key.pem", "-out", "server.csr"], dir);
  openssl(["x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca-key.pem",
    "-CAcreateserial", "-days", "2", "-extfile", "leaf.ext", "-out", "server.pem"], dir);
  return {
    ca: join(dir, "ca.pem"),
    cert: join(dir, "server.pem"),
    key: join(dir, "server-key.pem"),
  };
}

// CLI: node e2e/lib/tls.mjs <dir>
if (import.meta.url === `file://${process.argv[1]}`) {
  createTlsMaterial(process.argv[2]);
}
