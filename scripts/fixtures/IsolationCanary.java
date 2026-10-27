import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

// Disposable probe endpoint, never a target business oracle or an Internet service.
class IsolationCanary {
    public static void main(String[] args) throws Exception {
        if (args.length != 1 || !args[0].matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException("A fresh probe identity is required");
        }
        byte[] marker = args[0].getBytes(StandardCharsets.US_ASCII);
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", 18080), 4);
        server.createContext("/", exchange -> {
            if (!exchange.getRequestMethod().equals("GET") || !exchange.getRequestURI().toString().equals("/")) {
                exchange.sendResponseHeaders(404, -1);
            } else {
                exchange.sendResponseHeaders(200, marker.length);
                exchange.getResponseBody().write(marker);
            }
            exchange.close();
        });
        server.start();
    }
}
