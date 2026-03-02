package com.autotest.platform.config;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.rabbit.listener.SimpleMessageListenerContainer;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RabbitMQConfig {
    
    // Queue names
    public static final String TEST_EXECUTION_QUEUE = "test.execution.queue";
    public static final String TEST_EXECUTION_RESULT_QUEUE = "test.execution.result.queue";
    public static final String AI_GENERATION_QUEUE = "ai.generation.queue";
    public static final String NOTIFICATION_QUEUE = "notification.queue";
    
    // Exchange names
    public static final String TEST_EXCHANGE = "test.exchange";
    public static final String AI_EXCHANGE = "ai.exchange";
    
    // Routing keys
    public static final String TEST_EXECUTION_ROUTING_KEY = "test.execution";
    public static final String TEST_EXECUTION_RESULT_ROUTING_KEY = "test.execution.result";
    public static final String AI_GENERATION_ROUTING_KEY = "ai.generation";
    
    @Bean
    public Queue testExecutionQueue() {
        return QueueBuilder.durable(TEST_EXECUTION_QUEUE)
                .withArgument("x-dead-letter-exchange", "")
                .withArgument("x-dead-letter-routing-key", TEST_EXECUTION_QUEUE + ".dlq")
                .build();
    }
    
    @Bean
    public Queue testExecutionResultQueue() {
        return new Queue(TEST_EXECUTION_RESULT_QUEUE, true);
    }
    
    @Bean
    public Queue aiGenerationQueue() {
        return new Queue(AI_GENERATION_QUEUE, true);
    }
    
    @Bean
    public Queue notificationQueue() {
        return new Queue(NOTIFICATION_QUEUE, true);
    }
    
    @Bean
    public DirectExchange testExchange() {
        return new DirectExchange(TEST_EXCHANGE);
    }
    
    @Bean
    public DirectExchange aiExchange() {
        return new DirectExchange(AI_EXCHANGE);
    }
    
    @Bean
    public Binding testExecutionBinding(Queue testExecutionQueue, DirectExchange testExchange) {
        return BindingBuilder.bind(testExecutionQueue)
                .to(testExchange)
                .with(TEST_EXECUTION_ROUTING_KEY);
    }
    
    @Bean
    public Binding testExecutionResultBinding(Queue testExecutionResultQueue, DirectExchange testExchange) {
        return BindingBuilder.bind(testExecutionResultQueue)
                .to(testExchange)
                .with(TEST_EXECUTION_RESULT_ROUTING_KEY);
    }
    
    @Bean
    public Binding aiGenerationBinding(Queue aiGenerationQueue, DirectExchange aiExchange) {
        return BindingBuilder.bind(aiGenerationQueue)
                .to(aiExchange)
                .with(AI_GENERATION_ROUTING_KEY);
    }
    
    @Bean
    public MessageConverter jsonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }
    
    @Bean
    public RabbitTemplate rabbitTemplate(ConnectionFactory connectionFactory) {
        RabbitTemplate template = new RabbitTemplate(connectionFactory);
        template.setMessageConverter(jsonMessageConverter());
        return template;
    }
    
    @Bean
    public SimpleMessageListenerContainer container(ConnectionFactory connectionFactory) {
        SimpleMessageListenerContainer container = new SimpleMessageListenerContainer();
        container.setConnectionFactory(connectionFactory);
        return container;
    }
}
