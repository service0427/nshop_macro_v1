module.exports = {
  apps: [
    {
      name: "nshop-api",
      script: "app.py",
      cwd: "/home/tech/nshop_api_v1",
      interpreter: "python3",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "400M",
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1"
      }
    },
    {
      name: "nshop-pool-daemon",
      script: "daemon_pool_maintainer.py",
      cwd: "/home/tech/nshop_api_v1",
      interpreter: "python3",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "400M",
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
