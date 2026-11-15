target "alpine" {
  context = "alpine"
}

target "python" {
  contexts = {
    local-alpine = "target:alpine"
  }
  args = {
    BUILD_FROM = "local-alpine"
  }
  output = ["type=cacheonly"]
}
