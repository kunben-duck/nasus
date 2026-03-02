package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "test_steps")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TestStep {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(nullable = false)
    private Integer stepOrder;
    
    @Column(nullable = false, length = 500)
    private String action;
    
    @Column(length = 500)
    private String expectedResult;
    
    @Column(length = 500)
    private String testData;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "test_case_id", nullable = false)
    private TestCase testCase;
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;
}
