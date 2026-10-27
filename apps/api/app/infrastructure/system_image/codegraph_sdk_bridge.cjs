"use strict";

// Drive the public SDK only. The parent owns the immutable input, limits and process group.
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const [sdkPath, root, expectedVersion, maxNodes, maxEdges, maxFiles] = process.argv.slice(2);
  const limits = [maxNodes, maxEdges, maxFiles].map(Number);
  if (limits.some((limit) => !Number.isSafeInteger(limit) || limit < 1)) throw new Error("invalid limits");
  const manifest = JSON.parse(fs.readFileSync(path.join(sdkPath, "package.json"), "utf8"));
  if (manifest.name !== "@colbymchenry/codegraph" || manifest.version !== expectedVersion) throw new Error("SDK changed");
  console.log = (...values) => process.stderr.write(values.join(" ") + "\n");
  const { CodeGraph, silentLogger, setLogger } = require(sdkPath);
  if (typeof CodeGraph?.init !== "function" || typeof setLogger !== "function" || !silentLogger) {
    throw new Error("public SDK exports changed");
  }
  setLogger(silentLogger);
  const graph = await CodeGraph.init(root, { index: false });
  const methods = ["indexAll", "getStats", "getFiles", "getNodesInFile", "getOutgoingEdges",
    "getIndexState", "getPendingReferenceCount", "close"];
  let result;
  try {
    if (methods.some((name) => typeof graph[name] !== "function")) throw new Error("public SDK methods changed");
    await graph.indexAll();
    const stats = graph.getStats();
    if (stats.nodeCount > limits[0] || stats.edgeCount > limits[1] || stats.fileCount > limits[2]) {
      throw new Error("projection exceeds approved capacity");
    }
    const files = graph.getFiles().sort((a, b) => a.path.localeCompare(b.path));
    const nodes = [];
    const edges = [];
    for (const file of files) {
      for (const node of graph.getNodesInFile(file.path)) {
        nodes.push({
          id: node.id, kind: node.kind, name: node.name, qualified_name: node.qualifiedName,
          path: node.filePath, language: node.language, start_line: node.startLine, end_line: node.endLine,
        });
        for (const edge of graph.getOutgoingEdges(node.id)) {
          edges.push({ source: edge.source, target: edge.target, kind: edge.kind,
            provenance: edge.provenance || "unknown", line: edge.line ?? null,
            column: edge.column ?? null, metadata: edge.metadata ?? null });
        }
        if (nodes.length > limits[0] || edges.length > limits[1]) throw new Error("projection grew beyond capacity");
      }
    }
    nodes.sort((a, b) => a.id.localeCompare(b.id));
    edges.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    result = {
      schema: "nasus.codegraph-sdk-projection.v2", version: manifest.version,
      sdk_contract: { schema: "nasus.codegraph-public-sdk-contract.v1", package_name: manifest.name,
        package_version: manifest.version, entry_point: "package_public_entry",
        public_operations: ["CodeGraph.init", "setLogger", ...methods.map((name) => "graph." + name)],
        result_schema: "nasus.codegraph-sdk-projection.v2" },
      state: graph.getIndexState(), pending_references: graph.getPendingReferenceCount(),
      stats: { nodes: stats.nodeCount, edges: stats.edgeCount, files: stats.fileCount },
      files: files.map((file) => ({ path: file.path, node_count: file.nodeCount,
        error_count: (file.errors || []).length })), nodes, edges,
    };
  } finally {
    graph.close();
  }
  // A successful close is part of this exercised contract, not an advertised MCP tool list.
  process.stdout.write(JSON.stringify(result));
}

main().catch(() => {
  // Provider diagnostics can include raw source or absolute paths.
  process.stderr.write("CodeGraph SDK projection unavailable.\n");
  process.exitCode = 1;
});
