// The same writer can be called at a chosen reporting boundary in LibTorch.
// This example deliberately needs only a C++17 compiler.
#include "metrics_jsonl_writer.hpp"
#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
  if (argc != 2) { std::cerr << "Usage: record_metrics EMPTY_DIRECTORY\n"; return 2; }
  try {
    const std::filesystem::path root(argv[1]);
    if (std::filesystem::exists(root)) throw std::runtime_error("destination exists");
    std::filesystem::create_directories(root);
    std::ofstream(root / "manifest.json") << R"({"run_id":"synthetic-cpp-run","project":"lens-cpp-demo","name":"cpp-scalars","config":{"learning_rate":0.01,"source":"synthetic"}})";
    portable_experiment::MetricsJsonlWriter writer(root / "metrics.jsonl", "synthetic-cpp-run");
    for (int step=0; step<5; ++step) writer.Write(step, {{"train/loss", 1.0/(step+1)}, {"eval/accuracy", 0.5+step*0.1}}, step*0.1);
    std::ofstream(root / "completed.json") << R"({"exit_code":0})";
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
