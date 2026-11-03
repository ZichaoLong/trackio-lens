#pragma once

// Project-owned, header-only C++17 scalar metric writer. Copy and adapt this
// file; do not include it from an installed skill directory at runtime.

#include <chrono>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <variant>

namespace portable_experiment {

using ContextValue =
    std::variant<std::monostate, bool, std::int64_t, double, std::string>;

enum class OpenMode {
  create_new,
  append_existing,
};

struct WriterState {
  std::uint64_t next_sequence = 0;
  std::int64_t last_step = -1;
  double last_elapsed_seconds = -1.0;
};

class MetricsJsonlWriter {
 public:
  MetricsJsonlWriter(const std::filesystem::path& path, std::string run_id,
                     WriterState state = {},
                     OpenMode mode = OpenMode::create_new)
      : path_(path),
        run_id_(std::move(run_id)),
        state_(state) {
    if (run_id_.empty()) {
      throw std::invalid_argument("run_id must not be empty");
    }
    if (state_.last_step < -1 ||
        !std::isfinite(state_.last_elapsed_seconds) ||
        state_.last_elapsed_seconds < -1.0) {
      throw std::invalid_argument("invalid initial writer state");
    }
    const bool exists = std::filesystem::exists(path_);
    if (mode == OpenMode::create_new && exists) {
      throw std::runtime_error("refusing to overwrite existing metrics file");
    }
    if (mode == OpenMode::append_existing && !exists) {
      throw std::runtime_error("resume metrics file does not exist");
    }
    output_.open(path_, std::ios::out | std::ios::app | std::ios::binary);
    if (!output_) {
      throw std::runtime_error("cannot open metrics file");
    }
  }

  MetricsJsonlWriter(const MetricsJsonlWriter&) = delete;
  MetricsJsonlWriter& operator=(const MetricsJsonlWriter&) = delete;

  WriterState state() const noexcept { return state_; }

  void Write(std::int64_t step, const std::map<std::string, double>& metrics,
             double elapsed_seconds,
             const std::map<std::string, ContextValue>& context = {}) {
    if (step < 0) {
      throw std::invalid_argument("step must be nonnegative");
    }
    if (state_.last_step >= 0 && step < state_.last_step) {
      throw std::invalid_argument("step must not decrease");
    }
    if (metrics.empty()) {
      throw std::invalid_argument("metrics must not be empty");
    }
    if (!std::isfinite(elapsed_seconds) || elapsed_seconds < 0.0) {
      throw std::invalid_argument("elapsed_seconds must be finite and nonnegative");
    }
    if (state_.last_elapsed_seconds >= 0.0 &&
        elapsed_seconds < state_.last_elapsed_seconds) {
      throw std::invalid_argument("elapsed_seconds must not decrease");
    }

    std::ostringstream line;
    line << '{'
         << "\"schema_version\":1,"
         << "\"run_id\":" << Quote(run_id_) << ','
         << "\"sequence\":" << state_.next_sequence << ','
         << "\"timestamp\":" << Quote(UtcNow()) << ','
         << "\"step\":" << step << ','
         << "\"elapsed_seconds\":" << Number(elapsed_seconds) << ','
         << "\"metrics\":{";
    bool first = true;
    for (const auto& item : metrics) {
      ValidateName(item.first, "metric");
      if (!std::isfinite(item.second)) {
        throw std::invalid_argument("metric values must be finite");
      }
      if (!first) line << ',';
      first = false;
      line << Quote(item.first) << ':' << Number(item.second);
    }
    line << '}';
    if (!context.empty()) {
      line << ",\"context\":{";
      first = true;
      for (const auto& item : context) {
        ValidateName(item.first, "context");
        if (!first) line << ',';
        first = false;
        line << Quote(item.first) << ':' << ContextJson(item.second);
      }
      line << '}';
    }
    line << "}\n";

    output_ << line.str();
    output_.flush();
    if (!output_) {
      throw std::runtime_error("failed to append and flush metric event");
    }
    ++state_.next_sequence;
    state_.last_step = step;
    state_.last_elapsed_seconds = elapsed_seconds;
  }

 private:
  static void ValidateName(const std::string& value, const char* kind) {
    if (value.empty()) {
      throw std::invalid_argument(std::string(kind) + " name must not be empty");
    }
  }

  static std::string UtcNow() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t value = std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
#if defined(_WIN32)
    if (gmtime_s(&utc, &value) != 0) {
      throw std::runtime_error("cannot convert UTC timestamp");
    }
#else
    if (gmtime_r(&value, &utc) == nullptr) {
      throw std::runtime_error("cannot convert UTC timestamp");
    }
#endif
    std::ostringstream result;
    result << std::put_time(&utc, "%Y-%m-%dT%H:%M:%SZ");
    return result.str();
  }

  static std::string Number(double value) {
    std::ostringstream result;
    result << std::setprecision(std::numeric_limits<double>::max_digits10)
           << value;
    return result.str();
  }

  static std::string Quote(const std::string& value) {
    static const char* digits = "0123456789abcdef";
    std::ostringstream result;
    result << '"';
    for (const unsigned char ch : value) {
      switch (ch) {
        case '"': result << "\\\""; break;
        case '\\': result << "\\\\"; break;
        case '\b': result << "\\b"; break;
        case '\f': result << "\\f"; break;
        case '\n': result << "\\n"; break;
        case '\r': result << "\\r"; break;
        case '\t': result << "\\t"; break;
        default:
          if (ch < 0x20) {
            result << "\\u00" << digits[(ch >> 4) & 0x0f] << digits[ch & 0x0f];
          } else {
            result << static_cast<char>(ch);
          }
      }
    }
    result << '"';
    return result.str();
  }

  static std::string ContextJson(const ContextValue& value) {
    if (std::holds_alternative<std::monostate>(value)) return "null";
    if (const auto* item = std::get_if<bool>(&value)) {
      return *item ? "true" : "false";
    }
    if (const auto* item = std::get_if<std::int64_t>(&value)) {
      return std::to_string(*item);
    }
    if (const auto* item = std::get_if<double>(&value)) {
      if (!std::isfinite(*item)) {
        throw std::invalid_argument("context number must be finite");
      }
      return Number(*item);
    }
    return Quote(std::get<std::string>(value));
  }

  std::filesystem::path path_;
  std::string run_id_;
  WriterState state_;
  std::ofstream output_;
};

}  // namespace portable_experiment
